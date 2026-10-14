import requests
from typing import Optional, Dict, Any, Tuple
import config

def fetch_tweet_metadata(url: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    The Eyes (Fast Path):
    Fetches raw tweet metadata from vxtwitter API in milliseconds.
    Returns (data_dict, error_string).
    """
    # Normalize X / Twitter URL to API endpoint
    api_url = url.replace("https://x.com", config.VX_TWITTER_API)
    api_url = api_url.replace("https://twitter.com", config.VX_TWITTER_API)
    api_url = api_url.split("?")[0].rstrip("/")

    # vxtwitter blocks standard browser User-Agents with 403, but accepts TelegramBot / curl
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
            return data, None
        except ValueError:
            return None, "Invalid metadata format (API returned blank/HTML)"

    except Exception as e:
        return None, f"Network error fetching metadata: {str(e)}"
