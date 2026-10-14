from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel
from typing import Optional, List
import config
from features.x.adapter import XAdapter
from core.text_cleaner import MessageCleaner

router = APIRouter(prefix="/api/v1", tags=["scraper"])

class ScrapeRequest(BaseModel):
    url: str
    signature: Optional[str] = ""
    filter_mode: Optional[int] = 1

class ScrapeResponse(BaseModel):
    platform: str
    content_id: str
    author: str
    original_caption: str
    cleaned_caption: str
    media_count: int
    media_urls: List[str]

def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if not x_api_key or x_api_key != config.API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing X-API-Key header")
    return x_api_key

@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "Mister_Scraper", "version": "1.0.0"}

@router.post("/scrape", response_model=ScrapeResponse, dependencies=[Depends(verify_api_key)])
async def scrape_post(req: ScrapeRequest):
    """Headless endpoint for Mister_Chief or external consumers to scrape and clean an X post."""
    scraped = XAdapter.get_single_post(req.url)
    if not scraped:
        raise HTTPException(status_code=404, detail="Post not found or media unavailable")

    cleaned = MessageCleaner.clean(
        text=scraped.caption,
        mode=req.filter_mode,
        signature=req.signature
    )

    return ScrapeResponse(
        platform=scraped.platform,
        content_id=scraped.content_id,
        author=scraped.author,
        original_caption=scraped.caption,
        cleaned_caption=cleaned,
        media_count=len(scraped.media_list),
        media_urls=[m.get("url") for m in scraped.media_list if m.get("url")]
    )
