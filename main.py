"""Entry point — runs Telegram bot + monitor loop together."""
import asyncio
import logging
from telegram.ext import Application

from config import TG_BOT_TOKEN
import database as db
from bot import setup_handlers
from monitor import monitor_loop

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def post_init(app: Application):
    """Start monitor loop after bot is initialized."""
    db.init_db()
    db.cleanup_old(days=7)
    asyncio.create_task(monitor_loop(app))
    logger.info("Bot started, monitor loop launched")


def main():
    if not TG_BOT_TOKEN:
        print("ERROR: TG_BOT_TOKEN not set in .env")
        return

    app = Application.builder().token(TG_BOT_TOKEN).post_init(post_init).build()
    setup_handlers(app)

    logger.info("Starting bot...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
