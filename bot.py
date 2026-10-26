import asyncio

# Create a single event loop before Pyrogram/Motor are used
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

import logging
import os
import time

import aiohttp
from aiohttp import web
from pyrogram import Client, idle
from pyrogram.enums import ParseMode

from config import API_HASH, API_ID, BOT_TOKEN, PORT
from database import db
import stream
import weblinks
from helpers import log_event, now_ist, revoke_expired_joins, set_menu
import compat
import smallcaps

compat.patch()  # must run before smallcaps.patch()
smallcaps.patch()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("filestore")

app = Client(
    "filestore",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=dict(root="plugins"),
    parse_mode=ParseMode.HTML,
    in_memory=True,
)


async def web_server():
    async def root(_):
        return web.json_response({"status": "running"})

    w = web.Application()
    stream.setup(w, app)
    weblinks.setup(w, app)
    w.add_routes([web.get("/health", root)])
    runner = web.AppRunner(w)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("Web server on :%s", PORT)


async def delete_loop():
    """Auto-delete queue (stored in Mongo, survives restarts)."""
    while True:
        try:
            async for d in db.dq.find({"at": {"$lte": time.time()}}):
                try:
                    await app.delete_messages(d["chat_id"], d["ids"])
                except Exception as e:
                    log.warning("delete failed: %s", e)
                await db.dq.delete_one({"_id": d["_id"]})
            await db.tokens.delete_many({"at": {"$lt": time.time() - 86400}})
            await revoke_expired_joins(app)
        except Exception as e:
            log.error("delete loop: %s", e)
        await asyncio.sleep(20)


async def ping_loop():
    """Self-ping to keep the Render free plan awake."""
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        return
    while True:
        await asyncio.sleep(600)
        try:
            async with aiohttp.ClientSession() as s:
                await s.get(url.rstrip("/") + "/health", timeout=aiohttp.ClientTimeout(total=20))
        except Exception:
            pass


async def reminder_loop():
    """Premium expiry reminders, checked every 10 minutes."""
    from plugins.premium import send_reminders

    await asyncio.sleep(60)
    while True:
        try:
            await send_reminders(app)
        except Exception as e:
            log.error("reminder loop: %s", e)
        await asyncio.sleep(600)


async def startup_notice():
    """After a restart: edit the /restart message and post #BotRestarted to the log channel."""
    by = None
    marker = await db.cfg.find_one({"_id": "restart"})
    if marker:
        await db.cfg.delete_one({"_id": "restart"})
        by = marker.get("by")
        try:
            await app.edit_message_text(marker["chat_id"], marker["msg_id"], "✅ <b>Bot restarted successfully!</b>")
        except Exception:
            pass
    reason = f"Manual /restart (by <code>{by}</code>)" if by else "Deploy / crash / auto restart"
    await log_event(
        app,
        f"#BotRestarted\n\n🤖 Bot: @{app.me.username}\n📅 Time: {now_ist()}\n♻️ Reason: {reason}",
    )


async def main():
    await db.load()
    await web_server()
    await app.start()
    log.info("Bot started as @%s", app.me.username)
    await set_menu(app)
    await startup_notice()
    asyncio.create_task(delete_loop())
    asyncio.create_task(ping_loop())
    asyncio.create_task(reminder_loop())
    await idle()
    await app.stop()


if __name__ == "__main__":
    loop.run_until_complete(main())
