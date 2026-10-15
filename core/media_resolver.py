import re
from pathlib import Path
from typing import List, Dict, Any

def sanitize_filename(name: str, max_length: int = 50) -> str:
    """
    Turns any raw post text or title into a safe, valid filesystem filename.
    """
    if not name:
        return "x_media"
    
    # Replace non-alphanumeric with underscores
    clean = re.sub(r'[^\w\s-]', '', name).strip()
    clean = re.sub(r'[-\s]+', '_', clean)
    return clean[:max_length] if clean else "x_media"

def resolve_extension(media_type: str, url: str = "") -> str:
    """
    Resolves correct file extension based on media type and URL.
    """
    if "video" in media_type.lower() or "mp4" in url.lower():
        return "mp4"
    if "gif" in media_type.lower():
        return "mp4"
    if "png" in url.lower():
        return "png"
    return "jpg"

def parse_media_list(data: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Extracts all media items from a vxtwitter JSON payload.
    """
    media_list = []
    
    # 1. Check direct media_extended (photos & videos)
    if "media_extended" in data and isinstance(data["media_extended"], list):
        for item in data["media_extended"]:
            url = item.get("url")
            m_type = item.get("type", "image")
            thumb_url = item.get("thumbnail_url")
            if url:
                entry = {"url": url, "type": m_type}
                if thumb_url:
                    entry["thumbnail_url"] = thumb_url
                media_list.append(entry)
                
    # 2. Check legacy single media_url
    elif "media_url" in data and data["media_url"]:
        entry = {
            "url": data["media_url"],
            "type": "video" if data.get("hasVideo") else "image"
        }
        if data.get("thumbnail_url"):
            entry["thumbnail_url"] = data.get("thumbnail_url")
        media_list.append(entry)
    return media_list

def extract_x_username(input_str: str) -> str:
    """
    Extracts the clean X username from various inputs:
    - '@elonmusk' -> 'elonmusk'
    - 'https://x.com/elonmusk' -> 'elonmusk'
    - 'https://x.com/elonmusk/media' -> 'elonmusk'
    - 'https://twitter.com/elonmusk' -> 'elonmusk'
    - 'elonmusk' -> 'elonmusk'
    """
    cleaned = input_str.strip().rstrip("/")
    # Strip URL schemes and domain
    for prefix in ["https://x.com/", "http://x.com/", "https://twitter.com/", "http://twitter.com/"]:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break

    # If it ends with /media, /status, etc., strip after the slash
    parts = cleaned.split("/")
    raw_user = parts[0].split("?")[0].strip()
    return raw_user.lstrip("@")


def extract_status_urls(text: str) -> List[str]:
    """
    Extracts all valid X / Twitter status URLs from a string.
    Works for single links or multiline/bulk text drops.
    Deduplicates while preserving order.
    """
    pattern = r'https?://(?:(?:www\.)?x\.com|(?:www\.)?twitter\.com)/[A-Za-z0-9_]+/status/\d+'
    raw_matches = re.findall(pattern, text)
    
    seen = set()
    cleaned = []
    for m in raw_matches:
        base = m.split("?")[0].rstrip("/")
        if base not in seen:
            seen.add(base)
            cleaned.append(base)
    return cleaned

