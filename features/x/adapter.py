from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from .fast_meta import fetch_tweet_metadata
from .scraper import scrape_profile_media
from core.media_resolver import parse_media_list

@dataclass
class ScrapedItem:
    """Standardized output structure for any scraped piece of content."""
    platform: str
    content_id: str
    content_url: str
    author: str
    caption: str
    media_list: List[Dict[str, str]] = field(default_factory=list) # [{'url': ..., 'type': 'video'|'image'}]

class XAdapter:
    """
    The Plug: Unifies single link extraction and profile harvesting
    into clean, normalized ScrapedItem objects.
    """
    @staticmethod
    def get_single_post(url: str) -> Optional[ScrapedItem]:
        """Fetches metadata for a single tweet URL."""
        data, error = fetch_tweet_metadata(url)
        if error or not data:
            return None

        tweet_id = url.split("?")[0].rstrip("/").split("/")[-1]
        author = data.get("user_screen_name", "")
        caption = data.get("text", "")
        media_list = parse_media_list(data)

        return ScrapedItem(
            platform="x",
            content_id=tweet_id,
            content_url=url,
            author=author,
            caption=caption,
            media_list=media_list
        )

    @staticmethod
    async def get_profile_posts(username: str, limit: int = 10) -> List[str]:
        """Harvests recent tweet links for a target username."""
        return await scrape_profile_media(username, limit=limit)
