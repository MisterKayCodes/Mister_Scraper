from aiogram import Dispatcher
from .menu import router as menu_router
from .quick_grab import router as quick_grab_router
from .sync_flow import router as sync_router
from .settings import router as settings_router

def register_all_handlers(dp: Dispatcher) -> None:
    """Registers all bot routers in proper hierarchy."""
    dp.include_router(menu_router)
    dp.include_router(quick_grab_router)
    dp.include_router(sync_router)
    dp.include_router(settings_router)
