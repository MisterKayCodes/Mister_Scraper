import requests
from pathlib import Path
from typing import Optional, Dict
import config

def download_file(
    url: str,
    target_path: Path,
    headers: Optional[Dict[str, str]] = None,
    chunk_size: int = 128 * 1024,
    progress_callback: Optional[callable] = None
) -> bool:
    """
    The Carrier (Hands):
    Downloads any media file using streaming 128KB chunks to prevent memory spikes.
    Emits progress_callback(downloaded_bytes, total_bytes) if provided.
    Returns True if download succeeded, False otherwise.
    """
    req_headers = headers or config.DEFAULT_HEADERS
    temp_path = target_path.with_suffix(f"{target_path.suffix}.tmp")

    try:
        with requests.get(url, headers=req_headers, stream=True, timeout=60) as r:
            r.raise_for_status()
            total_bytes = int(r.headers.get("content-length", 0))
            downloaded_bytes = 0

            with open(temp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded_bytes += len(chunk)
                        if progress_callback and total_bytes > 0:
                            try:
                                progress_callback(downloaded_bytes, total_bytes)
                            except Exception:
                                pass

        # Atomic rename once complete
        if temp_path.exists():
            temp_path.replace(target_path)
            return True

        return False

    except Exception as e:
        # Cleanup temporary partial download
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        return False
