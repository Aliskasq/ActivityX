"""Entry point — runs Telegram bot + monitor loop together."""
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, ContextTypes

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


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Suppress startup Conflict errors, log everything else."""
    import telegram
    if isinstance(context.error, telegram.error.Conflict):
        logger.debug("Conflict (normal at startup), ignoring")
        return
    logger.error(f"Unhandled error: {context.error}", exc_info=context.error)


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
    app.add_error_handler(error_handler)

    logger.info("Starting bot...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
