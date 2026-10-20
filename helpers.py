import asyncio
import base64
import hashlib
import hmac
import html
import json
import logging
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

import aiohttp
from pyrogram import filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import FloodWait, MessageNotModified, UserNotParticipant
from pyrogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault
from pyrogram.types import InlineKeyboardButton as Btn
from pyrogram.types import InlineKeyboardMarkup as Markup

from config import BOT_TOKEN, OWNER_ID
from database import db
from smallcaps import sc

log = logging.getLogger("filestore")

# temporary admin state: {uid: {"mode": ...}}
STATE = {}
CANCEL = set()  # delivery cancel flags (user ids)


# ---------------- log channel ----------------
IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> str:
    return datetime.now(IST).strftime("%d %b %Y, %I:%M:%S %p IST")


async def log_event(client, text):
    chan = db.get("log_channel")
    if not chan:
        return
    try:
        await client.send_message(int(chan), text, disable_web_page_preview=True)
    except Exception as e:
        log.warning("log channel send failed: %s", e)


# ---------------- menu button (bot commands) ----------------
USER_CMDS = [
    ("start", "Start the bot"),
    ("plans", "View premium plans"),
    ("myplan", "Your premium status"),
]
ADMIN_CMDS = [
    ("genlink", "Generate a link for a file or message"),
    ("batch", "Create a batch link from channel posts"),
    ("custom_batch", "Create a custom batch of files"),
    ("settings", "Open the settings panel"),
    ("setdb", "Set the database channel"),
    ("addfsub", "Add a force-sub channel"),
    ("delfsub", "Remove a force-sub channel"),
    ("fsubs", "List force-sub channels"),
    ("addpremium", "Grant premium to a user"),
    ("removepremium", "Remove premium from a user"),
    ("premiums", "List premium users"),
    ("testverify", "Test the verification API"),
    ("stats", "Show bot statistics"),
    ("broadcast", "Broadcast a message to all users"),
    ("cancel", "Cancel the current action"),
    ("setlog", "Set the log channel"),
    ("help", "Admin commands guide"),
]
OWNER_CMDS = [
    ("addadmin", "Add an admin"),
    ("deladmin", "Remove an admin"),
    ("admins", "List admins"),
    ("restart", "Restart the bot"),
]


async def set_admin_menu(client, uid):
    if not uid:
        return
    cmds = USER_CMDS + ADMIN_CMDS + (OWNER_CMDS if uid == OWNER_ID else [])
    try:
        await client.set_bot_commands([BotCommand(c, sc(d)) for c, d in cmds], scope=BotCommandScopeChat(uid))
    except Exception as e:  # the admin may not have started the bot yet
        log.warning("admin menu failed for %s: %s", uid, e)


async def clear_admin_menu(client, uid):
    try:
        await client.delete_bot_commands(scope=BotCommandScopeChat(uid))
    except Exception as e:
        log.warning("clear menu failed for %s: %s", uid, e)


async def set_menu(client):
    await client.set_bot_commands([BotCommand(c, sc(d)) for c, d in USER_CMDS], scope=BotCommandScopeDefault())
    ids = {OWNER_ID}
    async for a in db.admins.find({}):
        ids.add(a["_id"])
    for uid in ids:
        await set_admin_menu(client, uid)


async def edit_msg(msg, text, kb=None):
    """Edits both text and photo (caption) messages."""
    try:
        if msg.photo or msg.video or msg.document or msg.animation:
            return await msg.edit_caption(text, reply_markup=kb)
        return await msg.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except MessageNotModified:
        pass


# ---------------- base64 ----------------
def b64e(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def b64d(s: str) -> str:
    return base64.urlsafe_b64decode((s + "=" * (-len(s) % 4)).encode()).decode()


def make_link(client, raw: str) -> str:
    return f"https://t.me/{client.me.username}?start={b64e(raw)}"


# ---------------- misc ----------------
async def _admin(_, __, m):
    return bool(m.from_user) and await db.is_admin(m.from_user.id)


admin_f = filters.create(_admin)


# ---------------- streaming (premium) ----------------
_SECRET = hashlib.sha256(BOT_TOKEN.encode()).digest()


def base_url() -> str:
    return (db.get("stream_base_url") or "").strip().rstrip("/")


def media_of(msg):
    for a in ("video", "audio", "voice", "animation", "video_note", "document"):
        x = getattr(msg, a, None)
        if x:
            return x
    return None


def is_streamable(msg) -> bool:
    x = media_of(msg)
    if not x:
        return False
    if msg.video or msg.audio or msg.voice or msg.animation or msg.video_note:
        return True
    return (getattr(x, "mime_type", "") or "").startswith(("video/", "audio/"))


def _sig(p: str) -> str:
    return hmac.new(_SECRET, p.encode(), hashlib.sha256).hexdigest()[:24]


def make_token(chat, mid, uid, ttl) -> str:
    p = b64e(f"{chat}_{mid}_{uid}_{int(time.time() + ttl)}")
    return f"{p}.{_sig(p)}"


def parse_token(tok):
    try:
        p, sig = tok.rsplit(".", 1)
        if not hmac.compare_digest(sig, _sig(p)):
            return None
        chat, mid, uid, exp = map(int, b64d(p).split("_"))
        return (chat, mid, uid) if exp >= time.time() else None
    except Exception:
        return None


async def stream_markup(uid, msg):
    """Only premium users and admins get the '▶️ Stream' button."""
    if not db.get("stream_enabled") or not base_url() or not is_streamable(msg):
        return None
    if not (await db.is_premium(uid) or await db.is_admin(uid)):
        return None
    tok = make_token(msg.chat.id, msg.id, uid, int(db.get("stream_expire") or 21600))
    return Markup([[Btn("▶️ Stream / Play", url=f"{base_url()}/watch/{tok}")]])


def sponsor_rows():
    url = (db.get("sponsor_url") or "").strip()
    if url.startswith("@"):
        url = f"https://t.me/{url[1:]}"
    return [[Btn(db.get("sponsor_label") or "🤝 Sponsor", url=url)]] if url.startswith("http") else []


def fmt_time(s) -> str:
    s, out = int(s), []
    for n, u in ((86400, "d"), (3600, "h"), (60, "m"), (1, "s")):
        if s >= n:
            out.append(f"{s // n}{u}")
            s %= n
    return " ".join(out) or "0s"


def fill(text: str, user=None, **kw) -> str:
    text = text or ""
    if user:
        text = text.replace("{mention}", user.mention).replace("{first}", user.first_name or "")
    for k, v in kw.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def parse_buttons(text):
    rows = []
    for line in (text or "").splitlines():
        if "|" in line:
            label, url = [x.strip() for x in line.split("|", 1)]
            if label and url.startswith(("http", "tg://")):
                rows.append([Btn(label, url=url)])
    return rows


# ---------------- channel helpers ----------------
async def is_bot_admin(client, chat_id) -> bool:
    try:
        mem = await client.get_chat_member(chat_id, "me")
        return mem.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except Exception:
        return False


def fwd_info(m):
    chat = getattr(m, "forward_from_chat", None)
    mid = getattr(m, "forward_from_message_id", None)
    if chat and mid:
        return chat.id, mid
    fo = getattr(m, "forward_origin", None)
    if fo:
        chat = getattr(fo, "chat", None)
        mid = getattr(fo, "message_id", None)
        if chat and mid:
            return chat.id, mid
    return None


_LINK = re.compile(r"(?:https?://)?t\.me/(c/)?([\w\d_]+)/(\d+)")


async def parse_ref(client, m):
    """Extracts (chat_id, msg_id) from a forward or a t.me post link."""
    info = fwd_info(m)
    if info:
        return info
    if m.text:
        r = _LINK.search(m.text)
        if r:
            if r.group(1):
                return int("-100" + r.group(2)), int(r.group(3))
            chat = await client.get_chat(r.group(2))
            return chat.id, int(r.group(3))
    return None


# ---------------- force subscribe ----------------
async def not_joined(client, uid):
    missing = []
    async for ch in db.fsub.find({}):
        cid = ch["chat_id"]
        joined = False
        try:
            mem = await client.get_chat_member(cid, uid)
            joined = mem.status not in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)
        except UserNotParticipant:
            joined = False
        except Exception as e:  # e.g. bot is not an admin there -> do not block the user
            log.warning("fsub check failed for %s: %s", cid, e)
            joined = True
        if not joined and ch["mode"] == "request" and await db.has_req(uid, cid):
            joined = True
        if not joined:
            missing.append(ch)
    return missing


def fsub_markup(client, missing, payload):
    rows = [[Btn(f"📢 Join {ch['title']}", url=ch["link"])] for ch in missing]
    rows.extend(sponsor_rows())
    if payload:
        rows.append([Btn("🔄 Try Again", url=f"https://t.me/{client.me.username}?start={payload}")])
    return Markup(rows)


# ---------------- verification ----------------
async def next_stage(uid) -> int:
    """0 = no verification needed, otherwise the next stage (1 or 2)."""
    mode = int(db.get("verify_mode") or 0)
    if mode <= 0:
        return 0
    v = await db.verified.find_one({"_id": uid}) or {}
    age = time.time() - v.get("at", 0)
    passed = v.get("passed", 0)
    expire = int(db.get("verify_expire") or 0)
    gap = int(db.get("verify_gap") or 0)
    if mode == 1:
        stage = 0 if (passed >= 1 and age < expire) else 1
    elif passed >= 2:
        stage = 0 if age < expire else 1
    elif passed == 1:
        stage = 0 if age < gap else 2  # free access inside the gap, then the 2nd verification
    else:
        stage = 1
    if stage and not db.get(f"v{stage}_api_url"):
        return 0
    return stage


async def shorten(api_url, api_key, url):
    """Returns (short_url or None, debug_text)."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
    try:
        async with aiohttp.ClientSession(headers=headers) as s:
            async with s.get(
                api_url.strip(),
                params={"api": api_key.strip(), "url": url},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as r:
                status = r.status
                txt = (await r.text()).strip()
    except Exception as e:
        return None, f"Request error: {e}"
    try:
        data = json.loads(txt)
    except Exception:
        data = None
    if isinstance(data, dict):
        for k in ("shortenedUrl", "shortened_url", "short_url", "shortUrl", "url"):
            if isinstance(data.get(k), str) and data[k].startswith("http"):
                return data[k], txt
    if txt.startswith("http") and "\n" not in txt:
        return txt, txt
    return None, f"HTTP {status}: {txt[:300]}"


async def send_verify(client, m, stage, payload):
    uid = m.from_user.id
    token = secrets.token_urlsafe(8)
    await db.tokens.insert_one({"_id": token, "uid": uid, "stage": stage, "payload": payload, "at": time.time()})
    url = f"https://t.me/{client.me.username}?start=verify_{token}"
    short, err = await shorten(db.get(f"v{stage}_api_url"), db.get(f"v{stage}_api_key"), url)
    if not short:
        log.warning("verify %s shortener failed: %s", stage, err)
        try:
            await client.send_message(
                OWNER_ID, f"⚠️ <b>Verification {stage} error</b>\n<code>{html.escape(err)}</code>\n\nTest: /testverify {stage}"
            )
        except Exception:
            pass
        return await m.reply("⚠️ The verification service is not working right now. Please contact the admin.")
    rows = [[Btn("✅ Verify Now", url=short)]]
    if db.get("verify_tutorial"):
        rows.append([Btn("❓ How to Verify", url=db.get("verify_tutorial"))])
    text = fill(
        db.get("verify_text"),
        m.from_user,
        stage=stage,
        mode=db.get("verify_mode"),
        time=fmt_time(db.get("verify_expire")),
    )
    await m.reply(text, reply_markup=Markup(rows), disable_web_page_preview=True)


# ---------------- delivery ----------------
async def deliver(client, m, payload):
    uid = m.from_user.id
    try:
        parts = b64d(payload).split("_")
        kind = parts[0]
        if kind == "s":
            chat, ids = int(parts[1]), [int(parts[2])]
        elif kind == "b":
            chat, a, b = int(parts[1]), int(parts[2]), int(parts[3])
            ids = list(range(min(a, b), max(a, b) + 1))
        elif kind == "c":
            doc = await db.batches.find_one({"_id": parts[1]})
            if not doc:
                raise ValueError("batch missing")
            chat, ids = doc["chat_id"], doc["ids"]
        else:
            raise ValueError("bad kind")
    except Exception:
        return await m.reply("❌ This link is invalid or has expired.")

    CANCEL.discard(uid)
    cancelled = False
    wait = await m.reply(
        db.get("wait_text"),
        reply_markup=Markup([[Btn("❌ Cancel Delivery", callback_data="dl_cancel")]] + sponsor_rows()),
    )
    protect = bool(db.get("protect_content"))
    sent = []
    try:
        for i in range(0, len(ids), 100):
            msgs = await client.get_messages(chat, ids[i : i + 100])
            for msg in msgs:
                if uid in CANCEL:
                    cancelled = True
                    break
                if not msg or msg.empty:
                    continue
                rm = await stream_markup(uid, msg)
                for attempt in range(3):
                    try:
                        c = await msg.copy(uid, protect_content=protect, reply_markup=rm)
                        sent.append(c.id)
                        break
                    except FloodWait as e:
                        await asyncio.sleep(e.value + 1)
                    except Exception as e:
                        log.warning("copy failed: %s", e)
                        if rm is not None:  # if the button URL is rejected, resend without the button
                            rm = None
                            continue
                        break
                await asyncio.sleep(0.4)
            if cancelled:
                break
    except Exception as e:
        log.error("deliver error: %s", e)
        await m.reply("❌ Could not fetch the files. Please contact the admin.")
    try:
        await wait.delete()
    except Exception:
        pass

    if cancelled:
        CANCEL.discard(uid)
        await m.reply("❌ Delivery cancelled.")
    delay = int(db.get("auto_delete") or 0)
    if delay > 0 and db.get("premium_no_autodelete") and await db.is_premium(uid):
        delay = 0
    if sent and delay > 0:
        rows = sponsor_rows()
        note = await m.reply(
            fill(db.get("auto_delete_text"), m.from_user, time=fmt_time(delay)),
            reply_markup=Markup(rows) if rows else None,
        )
        sent.append(note.id)
        await db.schedule_delete(uid, sent, delay)
