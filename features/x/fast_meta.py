import requests
from typing import Optional, Dict, Any, Tuple
from loguru import logger
import config

def fetch_tweet_metadata(url: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    The Eyes (Fast Path):
    Fetches raw tweet metadata.
    Primary: api.fxtwitter.com (provides multi-resolution 720p/360p stream variants for fast Telegram upload).
    Fallback: api.vxtwitter.com
    Returns (data_dict, error_string).
    """
    clean_url = url.split("?")[0].rstrip("/")
    parts = clean_url.replace("https://", "").replace("http://", "").split("/")
    
    # Try FxTwitter API first to obtain stream quality variants
    try:
        if len(parts) >= 4 and parts[2] == "status":
            screen_name = parts[1]
            status_id = parts[3]
            fx_url = f"https://api.fxtwitter.com/{screen_name}/status/{status_id}"
            
            resp = requests.get(fx_url, headers={"User-Agent": "TelegramBot (like TwitterBot)"}, timeout=10)
            if resp.status_code == 200:
                fx_json = resp.json()
                tweet_data = fx_json.get("tweet")
                if tweet_data:
                    logger.info(f"[EYES] Fetched metadata via FxTwitter for status {status_id}")
                    # Transform fx format to standard Mister_Scraper format
                    return _normalize_fxtwitter_payload(tweet_data, clean_url), None
    except Exception as fx_err:
        logger.warning(f"[EYES] FxTwitter lookup had hiccup: {fx_err}, falling back to VxTwitter...")

    # Fallback to VxTwitter
    api_url = clean_url.replace("https://x.com", config.VX_TWITTER_API)
    api_url = api_url.replace("https://twitter.com", config.VX_TWITTER_API)
    api_headers = {"User-Agent": "TelegramBot (like TwitterBot)"}

    try:
        response = requests.get(
            api_url,
            headers=api_headers,
            timeout=15,
            verify=True
        )
        if response.status_code != 200:
            return None, f"Metadata unavailable (HTTP {response.status_code})"

        try:
            data = response.json()
            logger.info(f"[EYES] Fetched metadata via VxTwitter for {clean_url}")
            return data, None
        except ValueError:
            return None, "Invalid metadata format (API returned blank/HTML)"

    except Exception as e:
        logger.error(f"[EYES] VxTwitter network error: {e}")
        return None, f"Network error fetching metadata: {str(e)}"

def _normalize_fxtwitter_payload(tweet: Dict[str, Any], original_url: str) -> Dict[str, Any]:
    """
    Selects optimal HD stream preserving native aspect ratio (portrait vs landscape)
    without exceeding safe bandwidth limits.
    """
    import re
    media_extended = []
    media_obj = tweet.get("media", {})
    
    # Videos
    videos = media_obj.get("videos", [])
    for v in videos:
        chosen_url = v.get("url") # Default fallback
        variants = v.get("variants", [])
        native_w = v.get("width")
        native_h = v.get("height")
        duration = v.get("duration", 0)

        is_portrait = False
        if native_w and native_h:
            is_portrait = int(native_h) > int(native_w)

        mp4_variants = [var for var in variants if var.get("content_type") == "video/mp4"]
        chosen_w = native_w
        chosen_h = native_h

        if mp4_variants:
            # Sort by bitrate ascending
            mp4_variants.sort(key=lambda x: x.get("bitrate", 0))
            
            optimal = None
            if is_portrait:
                # Vertical/Phone video: prefer crisp portrait HD (720x1280 or 1080x1920) up to 5.5 Mbps
                under_5m = [var for var in mp4_variants if var.get("bitrate", 0) <= 5_500_000]
                optimal = under_5m[-1] if under_5m else mp4_variants[-1]
            else:
                # Landscape video: prefer 720p HD between 1.2M and 4.0M to avoid 1080p upload timeouts
                for var in mp4_variants:
                    br = var.get("bitrate", 0)
                    if 1_200_000 <= br <= 4_000_000:
                        optimal = var
                        break
                if not optimal:
                    under_5m = [var for var in mp4_variants if var.get("bitrate", 0) <= 5_000_000]
                    optimal = under_5m[-1] if under_5m else mp4_variants[0]
            
            chosen_url = optimal.get("url", chosen_url)
            
            # Extract actual stream resolution from URL if available (e.g. /vid/avc1/720x1280/...)
            res_match = re.search(r'/vid/(?:avc1/)?(\d+)x(\d+)/', chosen_url)
            if res_match:
                chosen_w = int(res_match.group(1))
                chosen_h = int(res_match.group(2))
                
            logger.info(f"[EYES] Selected stream {chosen_w}x{chosen_h} @ {optimal.get('bitrate', 0)} bps (portrait={is_portrait}) for video ID {v.get('id')}")

        media_extended.append({
            "type": "video",
            "url": chosen_url,
            "thumbnail_url": v.get("thumbnail_url"),
            "width": int(chosen_w) if chosen_w else None,
            "height": int(chosen_h) if chosen_h else None,
            "duration": int(float(duration)) if duration else 0
        })

    # Photos
    photos = media_obj.get("photos", [])
    for p in photos:
        media_extended.append({
            "type": "image",
            "url": p.get("url"),
            "width": p.get("width"),
            "height": p.get("height")
        })

    author_obj = tweet.get("author", {})
    return {
        "text": tweet.get("text", ""),
        "user_screen_name": author_obj.get("screen_name", ""),
        "user_name": author_obj.get("name", ""),
        "tweetURL": original_url,
        "media_extended": media_extended
    }
