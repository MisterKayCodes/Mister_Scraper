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

def parse_media_list(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extracts all media items from a vxtwitter/fxtwitter JSON payload with dimensions.
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
                if item.get("width"):
                    entry["width"] = int(item["width"])
                if item.get("height"):
                    entry["height"] = int(item["height"])
                if item.get("duration"):
                    entry["duration"] = int(float(item["duration"]))
                media_list.append(entry)
                
    # 2. Check legacy single media_url
    elif "media_url" in data and data["media_url"]:
        entry = {
            "url": data["media_url"],
            "type": "video" if data.get("hasVideo") else "image"
        }
        if data.get("thumbnail_url"):
            entry["thumbnail_url"] = data.get("thumbnail_url")
        if data.get("width"):
            entry["width"] = int(data["width"])
        if data.get("height"):
            entry["height"] = int(data["height"])
        if data.get("duration"):
            entry["duration"] = int(float(data["duration"]))
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


def sanitize_telegram_channel(input_str: str) -> str:
    """
    Sanitizes Telegram channel input so it's always valid for the Bot API:
    - 'https://t.me/MyChannel' -> '@MyChannel'
    - 't.me/MyChannel' -> '@MyChannel'
    - 't.me/joinchat/...' or '+...' -> preserved if link, but warn
    - '@MyChannel' -> '@MyChannel'
    - '-100123456789' -> '-100123456789'
    - 'MyChannel' -> '@MyChannel'
    """
    cleaned = input_str.strip()
    
    # Check numeric chat ID (e.g. -100123456789 or 123456789)
    if (cleaned.startswith("-") and cleaned[1:].isdigit()) or cleaned.isdigit():
        return cleaned

    # Strip web URL prefixes
    for prefix in ["https://t.me/", "http://t.me/", "t.me/"]:
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break

    # Clean query params or trailing slashes
    cleaned = cleaned.split("?")[0].rstrip("/")

    # If it's a join link (starts with '+' or 'joinchat/'), keep as is
    if cleaned.startswith("+") or cleaned.startswith("joinchat/"):
        return cleaned

    # Ensure public channels start with @
    if not cleaned.startswith("@"):
        cleaned = f"@{cleaned}"

    return cleaned

