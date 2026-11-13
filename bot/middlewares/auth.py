from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from loguru import logger

import config

GATE_MESSAGE = (
    "🔒 <b>Access Restricted</b>\n\n"
    "This X/Twitter scraping system is private and protected.\n"
    "To request access, activate a license, or inquire about custom automation, contact the operator:\n\n"
    "📲 <b>WhatsApp:</b> +234 912 159 1811"
)

GATE_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="💬 Message Me on WhatsApp",
                url="https://wa.me/2349121591811?text=Hello%2C%20I%20would%20like%20to%20request%20access%20to%20Mister%20Scraper"
            )
        ]
    ]
)

class GatekeeperMiddleware(BaseMiddleware):
    """
    Global authorization gatekeeper.
    Intercepts every incoming message or callback from unauthorized users
    and prompts them to message the owner on WhatsApp.
    """
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        # Allow configured admin IDs
        if user.id in config.ADMIN_IDS:
            return await handler(event, data)

        # Unauthorized visitor
        logger.warning(f"[GATEKEEPER] Blocked unauthorized access attempt by user_id={user.id} (@{user.username or 'no_username'})")

        if isinstance(event, Message):
            await event.answer(GATE_MESSAGE, reply_markup=GATE_KEYBOARD)
            return
        elif isinstance(event, CallbackQuery):
            await event.answer("🔒 Access restricted. Contact operator on WhatsApp.", show_alert=True)
            if event.message:
                await event.message.answer(GATE_MESSAGE, reply_markup=GATE_KEYBOARD)
            return

        return
