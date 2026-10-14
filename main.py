import asyncio
import logging
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

import config
from data.database import init_db
from bot.handlers import register_all_handlers
from services.queue_worker import conveyor_worker
from services.scheduler import run_scheduler_loop
from api import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("mister_scraper")

async def run_fastapi(app):
    """Runs uvicorn web server in async loop."""
    server_config = uvicorn.Config(
        app=app,
        host=config.API_HOST,
        port=config.API_PORT,
        log_level="warning"
    )
    server = uvicorn.Server(server_config)
    await server.serve()

async def main():
    logger.info("Initializing Mister_Scraper Database Vault...")
    await init_db()

    app = create_app()
    tasks = []

    # 1. Launch FastAPI Web Server
    tasks.append(asyncio.create_task(run_fastapi(app)))
    logger.info(f"API Server listening on http://{config.API_HOST}:{config.API_PORT}")

    # 2. Launch Telegram Bot (if BOT_TOKEN is present)
    if config.BOT_TOKEN:
        bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dp = Dispatcher()
        register_all_handlers(dp)

        # Launch Background Conveyor Worker
        tasks.append(asyncio.create_task(conveyor_worker(bot)))
        # Launch Background Scheduler
        tasks.append(asyncio.create_task(run_scheduler_loop()))
        # Launch Bot Polling
        tasks.append(asyncio.create_task(dp.start_polling(bot)))
        logger.info("Telegram Bot and Background Harvester started.")
    else:
        logger.warning("BOT_TOKEN not provided in .env. Running in headless API-only mode.")

    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Mister_Scraper shutdown cleanly.")
