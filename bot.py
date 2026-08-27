import os
import asyncio
from aiohttp import web

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from config import BOT_TOKEN


# =========================
# CONFIG
# =========================

PORT = int(os.getenv("PORT", "10000"))

RENDER_EXTERNAL_URL = os.getenv(
    "RENDER_EXTERNAL_URL",
    ""
).rstrip("/")

WEBHOOK_PATH = f"/telegram/{BOT_TOKEN}"


# =========================
# TELEGRAM APPLICATION
# =========================

application = (
    Application.builder()
    .token(BOT_TOKEN)
    .build()
)


# =========================
# START MENU
# =========================

def main_menu():

    keyboard = [
        [
            InlineKeyboardButton(
                "👨‍💻 Developer",
                callback_data="developer"
            )
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = (
        "🎬 <b>VIDEO DOWNLOADER</b>\n\n"
        "Send me a public video URL.\n\n"
        "✨ Features:\n"
        "• 🎬 Video title\n"
        "• 🖼️ Thumbnail\n"
        "• ⏱️ Duration\n"
        "• 📦 File size\n"
        "• 📊 Download progress\n"
        "• ⚡ Speed & ETA\n"
        "• 🔄 Retry / Resume\n"
        "• 📥 Queue\n"
        "• ⭐ Priority\n"
        "• 🛑 Cancel download\n\n"
        "👨‍💻 <b>Developer:</b> MASTERMIND"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# =========================
# DEVELOPER BUTTON
# =========================

async def developer_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton(
                "👨‍💻 @Do_x_Die",
                url="https://t.me/Do_x_Die"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Back",
                callback_data="back"
            )
        ]
    ]

    text = (
        "👨‍💻 <b>Developer</b>\n\n"
        "Name: <b>MASTERMIND</b>\n"
        "Username: <b>@Do_x_Die</b>"
    )

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# BACK BUTTON
# =========================

async def back_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    text = (
        "🎬 <b>VIDEO DOWNLOADER</b>\n\n"
        "Send me a public video URL."
    )

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# =========================
# URL HANDLER
# =========================

async def handle_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    url = update.message.text.strip()

    if not url.startswith(
        ("http://", "https://")
    ):

        await update.message.reply_text(
            "❌ Please send a valid video URL."
        )

        return

    await update.message.reply_text(
        "🔎 <b>Analyzing video...</b>\n\n"
        "Please wait.",
        parse_mode="HTML"
    )

    # Downloader integration will be added
    # in downloader.py.

    # Temporary response for testing.
    await update.message.reply_text(
        "✅ URL received!\n\n"
        f"🔗 <code>{url}</code>\n\n"
        "📥 Downloader engine will process it.",
        parse_mode="HTML"
    )


# =========================
# ERROR HANDLER
# =========================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    print(
        "Telegram error:",
        context.error
    )


# =========================
# WEBHOOK SERVER
# =========================

async def telegram_webhook(
    request: web.Request
):

    data = await request.json()

    update = Update.de_json(
        data,
        application.bot
    )

    await application.process_update(
        update
    )

    return web.Response(
        text="OK"
    )


async def health_check(
    request: web.Request
):

    return web.Response(
        text="Video Downloader Bot is running."
    )


# =========================
# START WEB SERVER
# =========================

async def run():

    if not RENDER_EXTERNAL_URL:

        raise RuntimeError(
            "RENDER_EXTERNAL_URL is missing."
        )

    await application.initialize()

    await application.start()

    await application.bot.set_webhook(
        url=(
            RENDER_EXTERNAL_URL
            + WEBHOOK_PATH
        ),
        drop_pending_updates=True
    )

    server = web.Application()

    server.router.add_get(
        "/",
        health_check
    )

    server.router.add_post(
        WEBHOOK_PATH,
        telegram_webhook
    )

    runner = web.AppRunner(server)

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    )

    await site.start()

    print(
        f"Server running on port {PORT}"
    )

    print(
        "Telegram webhook configured."
    )

    try:

        await asyncio.Event().wait()

    finally:

        await application.stop()
        await application.shutdown()
        await runner.cleanup()


# =========================
# HANDLERS
# =========================

application.add_handler(
    CommandHandler(
        "start",
        start
    )
)

application.add_handler(
    CallbackQueryHandler(
        developer_callback,
        pattern="^developer$"
    )
)

application.add_handler(
    CallbackQueryHandler(
        back_callback,
        pattern="^back$"
    )
)

application.add_handler(
    MessageHandler(
        filters.TEXT
        & ~filters.COMMAND,
        handle_url
    )
)

application.add_error_handler(
    error_handler
)


# =========================
# ENTRY POINT
# =========================

if __name__ == "__main__":

    asyncio.run(run())
