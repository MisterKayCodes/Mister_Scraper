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
    Selects optimal 720p/HD stream for fast Telegram delivery without socket exhaustion.
    """
    media_extended = []
    media_obj = tweet.get("media", {})
    
    # Videos
    videos = media_obj.get("videos", [])
    for v in videos:
        chosen_url = v.get("url") # Default fallback
        variants = v.get("variants", [])
        
        # Sort variants to find 720p or closest optimal video (around 2-3 Mbps)
        # Avoid uncompressed 1080p 10Mbps monsters that crash TCP sockets
        mp4_variants = [var for var in variants if var.get("content_type") == "video/mp4"]
        if mp4_variants:
            # Sort by bitrate ascending
            mp4_variants.sort(key=lambda x: x.get("bitrate", 0))
            
            # Prefer variant with bitrate between 1.5 Mbps and 3.5 Mbps (crisp 720p)
            optimal = None
            for var in mp4_variants:
                br = var.get("bitrate", 0)
                if 1_200_000 <= br <= 4_000_000:
                    optimal = var
                    break
            
            # If no mid-range bitrate found, pick highest under 5 Mbps or middle variant
            if not optimal:
                under_5m = [var for var in mp4_variants if var.get("bitrate", 0) <= 5_000_000]
                if under_5m:
                    optimal = under_5m[-1]
                else:
                    optimal = mp4_variants[0]
            
            chosen_url = optimal.get("url", chosen_url)
            logger.info(f"[EYES] Selected optimal bitrate {optimal.get('bitrate', 0)} bps for video ID {v.get('id')}")

        media_extended.append({
            "type": "video",
            "url": chosen_url,
            "thumbnail_url": v.get("thumbnail_url")
        })

    # Photos
    photos = media_obj.get("photos", [])
    for p in photos:
        media_extended.append({
            "type": "image",
            "url": p.get("url")
        })

    author_obj = tweet.get("author", {})
    return {
        "text": tweet.get("text", ""),
        "user_screen_name": author_obj.get("screen_name", ""),
        "user_name": author_obj.get("name", ""),
        "tweetURL": original_url,
        "media_extended": media_extended
    }
