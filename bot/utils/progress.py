import time
import asyncio
from typing import Optional
from aiogram.types import Message

class TelegramProgressTracker:
    """
    Build Once, Reuse Forever:
    Throttled Telegram live progress bar updater.
    Complies with Telegram's strict 1.5s edit limit to prevent FLOOD_WAIT bans.
    """
    def __init__(
        self,
        status_message: Message,
        action_title: str = "Downloading Media",
        min_interval_seconds: float = 1.5,
        step_percent: int = 15
    ):
        self.status_message = status_message
        self.action_title = action_title
        self.min_interval = min_interval_seconds
        self.step_percent = step_percent
        self.last_edit_time = 0.0
        self.last_percent = -1

    def _render_bar(self, percent: int, current_mb: float, total_mb: float) -> str:
        """Formats visual unicode progress bar [■■■■■□□□□□]."""
        total_blocks = 10
        filled = int((percent / 100.0) * total_blocks)
        empty = total_blocks - filled
        bar = "■" * filled + "□" * empty

        return (
            f"⏳ <b>{self.action_title}...</b>\n\n"
            f"<code>[{bar}] {percent}%</code>\n"
            f"📦 <b>Size:</b> {current_mb:.1f} MB / {total_mb:.1f} MB"
        )

    async def update(self, downloaded_bytes: int, total_bytes: int) -> None:
        """Called by download worker as chunks arrive."""
        if total_bytes <= 0:
            return

        percent = min(100, int((downloaded_bytes / total_bytes) * 100))
        now = time.time()

        # Only edit if step_percent passed OR min_interval passed, or reached 100%
        percent_jump = (percent - self.last_percent) >= self.step_percent
        time_elapsed = (now - self.last_edit_time) >= self.min_interval
        is_complete = percent == 100

        if (percent_jump and time_elapsed) or is_complete:
            self.last_edit_time = now
            self.last_percent = percent
            current_mb = downloaded_bytes / (1024 * 1024)
            total_mb = total_bytes / (1024 * 1024)
            text = self._render_bar(percent, current_mb, total_mb)

            try:
                await self.status_message.edit_text(text, parse_mode="HTML")
            except Exception:
                pass  # Ignore Telegram MessageNotModified or transient edit hiccups


from pathlib import Path
from typing import AsyncGenerator
from aiogram.types import FSInputFile
from aiogram import Bot

class ProgressFSInputFile(FSInputFile):
    """
    Build Once, Reuse Forever:
    An FSInputFile that reports chunks uploaded to Telegram Bot API.
    Wires directly into TelegramProgressTracker for real-time upload progress bars.
    """
    def __init__(
        self,
        path: str | Path,
        tracker: Optional[TelegramProgressTracker] = None,
        filename: Optional[str] = None,
        chunk_size: int = 64 * 1024
    ):
        super().__init__(path=path, filename=filename, chunk_size=chunk_size)
        self.tracker = tracker
        self.file_path = Path(path)
        self.total_size = self.file_path.stat().st_size if self.file_path.exists() else 0
        self.uploaded_bytes = 0

    async def read(self, bot: Bot) -> AsyncGenerator[bytes, None]:
        async for chunk in super().read(bot):
            yield chunk
            self.uploaded_bytes += len(chunk)
            if self.tracker and self.total_size > 0:
                try:
                    await self.tracker.update(self.uploaded_bytes, self.total_size)
                except Exception:
                    pass

