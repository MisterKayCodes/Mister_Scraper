import asyncio
import time
from pathlib import Path
from typing import Optional, Union
from aiogram import Bot, types
from loguru import logger

import config
from core.media_resolver import resolve_extension
from services.downloader import download_file
from services.downloader import download_file
from bot.utils.progress import TelegramProgressTracker, ProgressFSInputFile


async def send_media_resilient(
    bot: Bot,
    target_chat: Union[int, str],
    media_url: str,
    media_type: str,
    caption: str,
    status_msg: Optional[types.Message] = None,
    thumbnail_url: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    duration: Optional[int] = None,
    max_retries: int = 2
) -> str | bool:
    """
    The Carrier (Resilient Sender):
    Build Once, Reuse Forever.

    Tier 1: Attempts instant Telegram Cloud-to-Cloud transfer via direct URL (0 bytes local upload, ~2s delivery).
    Tier 2: If Telegram rejects direct URL, downloads chunked with live progress bar and executes
            resilient local file upload with dynamic timeout, live upload percentage tracking, and video thumbnail.
    """
    is_video = "video" in media_type.lower() or media_url.endswith(".mp4")
    thumb_input = types.URLInputFile(thumbnail_url) if (is_video and thumbnail_url) else None

    # -------------------------------------------------------------
    # TIER 1: Direct Cloud-to-Cloud Transfer (Telegram downloads URL)
    # -------------------------------------------------------------
    logger.info(f"[SENDER] Attempting Tier 1 Direct Cloud transfer for {media_url[:60]} (dim={width}x{height})...")
    if status_msg:
        try:
            await status_msg.edit_text("⚡ <i>Fast cloud transfer in progress...</i>", parse_mode="HTML")
        except Exception:
            pass

    try:
        sent_msg = None
        if is_video:
            sent_msg = await bot.send_video(
                chat_id=target_chat,
                video=media_url,
                caption=caption,
                width=width,
                height=height,
                duration=duration,
                supports_streaming=True,
                parse_mode="HTML",
                request_timeout=90
            )
        else:
            sent_msg = await bot.send_photo(
                chat_id=target_chat,
                photo=media_url,
                caption=caption,
                parse_mode="HTML",
                request_timeout=45
            )
        
        file_id = ""
        if sent_msg and sent_msg.video:
            file_id = sent_msg.video.file_id
        elif sent_msg and sent_msg.photo:
            file_id = sent_msg.photo[-1].file_id

        logger.info(f"[SENDER] Tier 1 Cloud transfer SUCCESS for {target_chat} (file_id={file_id[:15]}...)")
        return file_id or "SUCCESS"

    except Exception as tier1_err:
        logger.warning(f"[SENDER] Tier 1 Cloud transfer failed ({tier1_err}). Dropping to Tier 2 Local Upload...")

    # -------------------------------------------------------------
    # TIER 2: Local Atomic Download + Multi-part Upload with Retries & Live Progress
    # -------------------------------------------------------------
    download_dir = Path(config.DOWNLOAD_DIR)
    download_dir.mkdir(exist_ok=True)
    ext = resolve_extension(media_type, media_url)
    timestamp = int(time.time() * 1000)
    local_path = download_dir / f"send_{timestamp}.{ext}"

    loop = asyncio.get_running_loop()
    dl_tracker = TelegramProgressTracker(status_msg, action_title="Downloading from X") if status_msg else None

    def sync_progress_bridge(downloaded: int, total: int):
        if dl_tracker:
            asyncio.run_coroutine_threadsafe(dl_tracker.update(downloaded, total), loop)

    if status_msg:
        try:
            await status_msg.edit_text("⏳ <i>Downloading 720p media from X...</i>", parse_mode="HTML")
        except Exception:
            pass

    download_ok = await asyncio.to_thread(
        download_file,
        media_url,
        local_path,
        None,
        128 * 1024,
        sync_progress_bridge
    )

    if not download_ok or not local_path.exists():
        logger.error(f"[SENDER] Tier 2 Download failed for {media_url}")
        return False

    # Calculate dynamic timeout based on file size (minimum 600s, + 25s per MB)
    file_size_mb = local_path.stat().st_size / (1024 * 1024)
    logger.info(f"[SENDER] Local file size: {file_size_mb:.2f} MB (Path: {local_path.name})")

    compressed_path = None
    # -------------------------------------------------------------
    # PRE-FLIGHT GUARD & AUTO-COMPRESSION (Telegram Bot API 50MB Limit)
    # -------------------------------------------------------------
    if is_video and file_size_mb >= 49.0:
        logger.warning(f"[SENDER] Video {local_path.name} is {file_size_mb:.2f} MB (>= 49 MB). Engaging auto-compression...")
        if status_msg:
            try:
                await status_msg.edit_text("⚙️ <i>Video exceeds 50MB. Compressing to fit Telegram limit...</i>", parse_mode="HTML")
            except Exception:
                pass

        try:
            import subprocess
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            compressed_path = download_dir / f"compressed_{timestamp}.mp4"

            # Target 42 MB to comfortably fit under 50 MB
            # target_bitrate = (42MB * 8) / duration
            dur = max(10, int(duration or 30))
            target_kbps = max(350, int((42 * 1024 * 8) / dur) - 128)  # minus 128k audio

            cmd = [
                ffmpeg_exe,
                "-y",
                "-i", str(local_path),
                "-vf", "scale='min(1280,iw)':-2",
                "-c:v", "libx264",
                "-b:v", f"{target_kbps}k",
                "-maxrate", f"{int(target_kbps * 1.3)}k",
                "-bufsize", f"{target_kbps * 2}k",
                "-preset", "veryfast",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                str(compressed_path)
            ]

            proc = await asyncio.to_thread(
                subprocess.run,
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=180
            )

            if proc.returncode == 0 and compressed_path.exists():
                comp_size_mb = compressed_path.stat().st_size / (1024 * 1024)
                logger.info(f"[SENDER] Compressed {file_size_mb:.2f} MB -> {comp_size_mb:.2f} MB successfully.")
                if comp_size_mb < 49.5:
                    local_path = compressed_path
                    file_size_mb = comp_size_mb
                else:
                    logger.warning(f"[SENDER] Compressed size still oversized: {comp_size_mb:.2f} MB")
            else:
                logger.warning(f"[SENDER] ffmpeg exited with returncode {proc.returncode}")
        except Exception as comp_err:
            logger.error(f"[SENDER] Auto-compression failed: {comp_err}")

    # If still > 49.5 MB after compression attempt, activate Option A: Fallback Link Button
    if is_video and file_size_mb >= 49.5:
        logger.warning(f"[SENDER] Video still exceeds 50MB ({file_size_mb:.2f} MB). Executing Option A Fallback...")
        try:
            # Build inline button to original post/video
            markup = None
            orig_tweet_url = media_url
            if "status/" in caption or "x.com" in media_url or "twimg" in media_url:
                markup = types.InlineKeyboardMarkup(
                    inline_keyboard=[[
                        types.InlineKeyboardButton(
                            text="🔗 Watch Full HD Video on X",
                            url=media_url if "x.com" in media_url else f"https://x.com"
                        )
                    ]]
                )

            fallback_text = f"📹 <b>HD Video (Oversized: {file_size_mb:.1f} MB)</b>\n\n{caption}"
            if len(fallback_text) > 4000:
                fallback_text = fallback_text[:4000]

            sent_msg = await bot.send_message(
                chat_id=target_chat,
                text=fallback_text,
                reply_markup=markup,
                parse_mode="HTML",
                disable_web_page_preview=False
            )
            logger.info(f"[SENDER] Option A Fallback post delivered to {target_chat} (msg_id={sent_msg.message_id})")
            return "SUCCESS_FALLBACK"
        except Exception as fallback_err:
            logger.error(f"[SENDER] Option A Fallback failed: {fallback_err}")
            return False
        finally:
            for p in [local_path, compressed_path]:
                if p and p.exists():
                    try:
                        p.unlink()
                    except Exception:
                        pass

    dynamic_timeout = max(600, int(file_size_mb * 25))
    # Download and scale thumbnail locally (Telegram strictly requires max 320x320 pixels JPEG)
    thumb_path = None
    thumb_input = None
    if is_video and thumbnail_url:
        try:
            thumb_path = download_dir / f"thumb_{timestamp}.jpg"
            import requests
            from PIL import Image
            from io import BytesIO

            r_thumb = await asyncio.to_thread(requests.get, thumbnail_url, timeout=10)
            if r_thumb.status_code == 200:
                img = Image.open(BytesIO(r_thumb.content)).convert("RGB")
                img.thumbnail((320, 320), Image.Resampling.LANCZOS)
                img.save(thumb_path, "JPEG", quality=85)
                thumb_input = types.FSInputFile(str(thumb_path))
                logger.info(f"[SENDER] Scaled thumbnail to {img.size} ({thumb_path.stat().st_size} bytes) for video")
        except Exception as thumb_err:
            logger.warning(f"[SENDER] Failed to prepare thumbnail: {thumb_err}")

    for attempt in range(1, max_retries + 1):
        action_label = "Uploading to Telegram (HD)" if not compressed_path else "Uploading Compressed Video"
        upload_tracker = TelegramProgressTracker(status_msg, action_title=action_label) if status_msg else None
        
        try:
            file_input = ProgressFSInputFile(local_path, tracker=upload_tracker)
            sent_msg = None
            if is_video:
                sent_msg = await bot.send_video(
                    chat_id=target_chat,
                    video=file_input,
                    caption=caption,
                    width=width,
                    height=height,
                    duration=duration,
                    thumbnail=thumb_input,
                    supports_streaming=True,
                    parse_mode="HTML",
                    request_timeout=dynamic_timeout
                )
            else:
                sent_msg = await bot.send_photo(
                    chat_id=target_chat,
                    photo=file_input,
                    caption=caption,
                    parse_mode="HTML",
                    request_timeout=dynamic_timeout
                )
            
            file_id = ""
            if sent_msg and sent_msg.video:
                file_id = sent_msg.video.file_id
            elif sent_msg and sent_msg.photo:
                file_id = sent_msg.photo[-1].file_id

            logger.info(f"[SENDER] Tier 2 Local Upload SUCCESS to {target_chat} on attempt {attempt} (file_id={file_id[:15]}...)")
            return file_id or "SUCCESS"

        except Exception as upload_err:
            logger.warning(f"[SENDER] Upload attempt {attempt}/{max_retries} failed: {upload_err}")
            if attempt < max_retries:
                if status_msg:
                    try:
                        await status_msg.edit_text(
                            f"⏳ <i>Upload timed out. Retrying attempt {attempt + 1}/{max_retries} in 3s...</i>",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                await asyncio.sleep(3)
            else:
                logger.error(f"[SENDER] Tier 2 All {max_retries} upload attempts failed for {target_chat}")

        finally:
            pass

    # Final cleanup of temp files
    for p in [local_path, compressed_path, thumb_path]:
        if p and p.exists():
            try:
                p.unlink()
            except Exception:
                pass

    return False

