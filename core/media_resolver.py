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
            if url:
                media_list.append({"url": url, "type": m_type})
                
    # 2. Check legacy single media_url
    elif "media_url" in data and data["media_url"]:
        media_list.append({
            "url": data["media_url"],
            "type": "video" if data.get("hasVideo") else "image"
        })
        
    return media_list
