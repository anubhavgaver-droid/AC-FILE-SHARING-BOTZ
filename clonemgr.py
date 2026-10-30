"""Clone bots: extra copies of this bot (same code) that run inside this process.

Every clone has its OWN database (settings, users, premium, links, channels ...), its own owner and its own
conversation state. Handlers are bound to their bot (see compat.bind_handler), so nothing leaks between bots.
"""
import asyncio
import base64
import hashlib
import logging
import os
import time

import aiohttp
from cryptography.fernet import Fernet

from config import API_HASH, API_ID, BOT_TOKEN
from database import BOTS, CURRENT, MAIN_DB, Bot, Database

log = logging.getLogger("clonemgr")


# ---------------- bot tokens are stored encrypted ----------------
def _fernet():
    secret = os.environ.get("CLONE_SECRET") or BOT_TOKEN  # set CLONE_SECRET once and never change it
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def encrypt(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt(blob: str) -> str:
    return _fernet().decrypt(blob.encode()).decode()


async def tg_get_me(token: str):
    """Asks Telegram who a bot token belongs to. Returns the bot's info (id, username ...) or None."""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://api.telegram.org/bot{token}/getMe", timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                data = await r.json()
    except Exception as e:
        log.info("getMe failed: %s", type(e).__name__)
        return None
    return data.get("result") if isinstance(data, dict) and data.get("ok") else None


# ---------------- starting / stopping clones ----------------
def all_bound(client) -> bool:
    """True when every handler of this client was bound to its bot. If not, the library did not call
    Client.add_handler for plugins and the clone could touch the wrong data, so it must not run."""
    groups = getattr(getattr(client, "dispatcher", None), "groups", None)
    if not groups:
        return False
    handlers = [h for g in groups.values() for h in g]
    return bool(handlers) and all(getattr(h, "_bot_bound", False) for h in handlers)


async def start_clone(doc):
    from pyrogram import Client
    from pyrogram.enums import ParseMode

    bot_id = doc["_id"]
    if bot_id in BOTS:
        return BOTS[bot_id]
    client = Client(
        f"clone_{bot_id}",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=decrypt(doc["token_enc"]),
        plugins=dict(root="plugins"),
        parse_mode=ParseMode.HTML,
        in_memory=True,
    )
    cdb = Database(cli=MAIN_DB.cli, name=f"{MAIN_DB.name}_c{bot_id}", owner_id=doc["owner"], is_main=False)
    bot = Bot(bot_id, client, cdb, is_main=False, username=doc.get("username", ""))
    client.bot_ctx = bot  # must be set before start(): handlers are bound while the plugins load
    await cdb.load()
    await client.start()
    if not all_bound(client):
        await client.stop()
        raise RuntimeError("This Pyrogram/Kurigram version cannot keep clone bots separate, so the clone was not started.")
    bot.username = getattr(client.me, "username", None) or bot.username
    BOTS[bot_id] = bot
    from helpers import set_menu

    token = CURRENT.set(bot)
    try:
        await set_menu(client)
    except Exception as e:
        log.info("clone menu failed: %s", e)
    finally:
        CURRENT.reset(token)
    return bot


async def stop_clone(bot_id):
    bot = BOTS.get(bot_id)
    if bot is None or bot.is_main:  # the main bot is never stopped (or dropped from the registry) from here
        return
    BOTS.pop(bot_id, None)
    try:
        await bot.client.stop()
    except Exception as e:
        log.info("stopping clone %s: %s", bot_id, e)


async def start_all():
    docs = [d async for d in MAIN_DB.clones.find({"status": "active"})]
    for d in docs:
        try:
            await start_clone(d)
            log.info("clone @%s started", d.get("username"))
        except Exception as e:
            log.error("clone %s did not start: %s", d["_id"], e)
            await MAIN_DB.clones.update_one({"_id": d["_id"]}, {"$set": {"status": "error", "error": str(e)[:200]}})
        await asyncio.sleep(1)


# ---------------- background jobs for every bot ----------------
async def for_each_bot(fn):
    """Runs `await fn(bot)` for every running bot with that bot's database selected.
    A failure in one bot never stops the others."""
    for bot in list(BOTS.values()):
        token = CURRENT.set(bot)
        try:
            await fn(bot)
        except Exception as e:
            log.error("job failed for bot %s: %s", bot.id, e)
        finally:
            CURRENT.reset(token)


async def maintenance_pass():
    """Auto-delete queue, old verification tokens, expired invite links - for the main bot and all clones."""
    from helpers import revoke_expired_joins

    async def one(bot):
        d = bot.db
        async for item in d.dq.find({"at": {"$lte": time.time()}}):
            try:
                await bot.client.delete_messages(item["chat_id"], item["ids"])
            except Exception as e:
                log.warning("delete failed: %s", e)
            await d.dq.delete_one({"_id": item["_id"]})
        await d.tokens.delete_many({"at": {"$lt": time.time() - 86400}})
        await revoke_expired_joins(bot.client)

    await for_each_bot(one)


async def reminders_pass(send_reminders):
    async def one(bot):
        await send_reminders(bot.client)

    await for_each_bot(one)
