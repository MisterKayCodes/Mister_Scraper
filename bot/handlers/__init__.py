from aiogram import Dispatcher
from .menu import router as menu_router
from .quick_grab import router as quick_grab_router
from .sync_flow import router as sync_router
from .source_manager import router as source_manager_router
from .deep_harvest import router as deep_harvest_router
from .settings import router as settings_router

def register_all_handlers(dp: Dispatcher) -> None:
    """
    Registers all bot routers in proper hierarchy.
    Menu, Sync, and Settings are registered before Quick Grab so that
    top-level menu buttons always interrupt any waiting_for_link state.
    source_manager and deep_harvest registered after sync so FSM takes priority.
    """
    dp.include_router(menu_router)
    dp.include_router(sync_router)
    dp.include_router(source_manager_router)
    dp.include_router(deep_harvest_router)
    dp.include_router(settings_router)
    dp.include_router(quick_grab_router)
