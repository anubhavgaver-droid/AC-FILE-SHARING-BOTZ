import asyncio
import html
import logging
import platform
import time

import pyrogram
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton as Btn
from pyrogram.types import InlineKeyboardMarkup as Markup

from config import BOT_VERSION
from database import db
from helpers import (
    cooldown_left,
    deliver,
    fill,
    fmt_time,
    fsub_markup,
    next_stage,
    not_joined,
    parse_buttons,
    send_verify,
    sponsor_rows,
    CANCEL,
    edit_msg,
    log_event,
    now_ist,
    secs_to_midnight,
)


log = logging.getLogger("start")


def welcome_link():
    link = (db.get("welcome_link") or "").strip()
    return link if link.startswith("http") else ""


def _card_body(text, link):
    # The link hides behind an invisible character: Telegram builds the clickable preview card
    # (image from the page) but no URL text is shown in the message.
    return f'{text}<a href="{html.escape(link, quote=True)}">\u200b</a>'


def _preview_options(link):
    from pyrogram.types import LinkPreviewOptions

    return LinkPreviewOptions(
        url=link,
        prefer_large_media=bool(db.get("welcome_preview_large")),
        show_above_text=bool(db.get("welcome_preview_above")),
    )


async def _with_preview(send, body, kb, link):
    """send(body, reply_markup=..., [link_preview_options=...]); the options are used when the library has them."""
    try:
        return await send(body, reply_markup=kb, link_preview_options=_preview_options(link))
    except (ImportError, TypeError):  # older library: Telegram still builds its default (small) card
        return await send(body, reply_markup=kb)


async def welcome_parts(user):
    text = fill(db.get("welcome_text"), user)
    rows = parse_buttons(db.get("welcome_buttons"))
    rows.extend(sponsor_rows())
    rows.append([Btn("💎 Premium Plans", callback_data="plans")])
    rows.append([Btn("✨ Features", callback_data="features"), Btn("ℹ️ About", callback_data="about")])
    if await db.is_admin(user.id):  # shown to admins/owner only
        rows.append([Btn("⚙️ Settings", callback_data="pg_main")])
    return text, Markup(rows)


async def welcome(client, m):
    text, kb = await welcome_parts(m.from_user)
    link = welcome_link()
    if link:  # preview-card style wins over the attached photo
        try:
            return await _with_preview(
                lambda body, **kw: client.send_message(m.chat.id, body, **kw), _card_body(text, link), kb, link
            )
        except Exception as e:
            log.warning("welcome card failed, using the normal welcome: %s", e)
    photo = db.get("welcome_photo")
    if photo:
        try:
            return await client.send_photo(m.chat.id, photo, caption=text, reply_markup=kb)
        except Exception:
            pass
    await m.reply(text, reply_markup=kb, disable_web_page_preview=True)


async def handle_verify(client, m, token):
    uid = m.from_user.id
    t = await db.tokens.find_one({"_id": token})
    by_secret = False
    if not t:  # "server first" flow: the bot receives the secret created on the website
        t = await db.tokens.find_one({"secret": token})
        by_secret = bool(t)
    if not t or t["uid"] != uid or time.time() - t["at"] > 3600:
        return await m.reply("❌ This verification link is invalid or has expired. Please open the file link again.")
    server_first = t.get("order") == "server_first"
    if server_first and not by_secret:
        return await m.reply("❌ Please start from the verification page on the website. Open the verification link again.")
    if t.get("via_server") and not t.get("confirmed"):
        return await m.reply(
            "❌ Please complete the verification on the website first. Open the verification link again."
        )
    # server first: the time spent on the shortener counts (from leaving our page)
    since = time.time() - (t.get("confirmed_at", t["at"]) if server_first else t["at"])
    if since < int(db.get("verify_min_time") or 0):
        return await m.reply("🚫 Bypass detected. Please complete the verification link properly.")
    await db.tokens.delete_one({"_id": t["_id"]})
    await db.verified.update_one(
        {"_id": uid}, {"$set": {"passed": t["stage"], "at": time.time()}}, upsert=True
    )
    mode = int(db.get("verify_mode") or 0)
    gap = int(db.get("verify_gap") or 0)
    if t["stage"] >= mode:
        await db.reset_free(uid)  # fully verified: free links start again once this access expires
    if t["stage"] < mode and gap <= 0 and db.get(f"v{t['stage'] + 1}_api_url"):
        return await send_verify(client, m, t["stage"] + 1, t["payload"])
    if t["stage"] < mode:
        reset = bool(db.get("verify_midnight_reset"))
        if reset and gap > secs_to_midnight():
            await m.reply(
                f"✅ Verification {t['stage']}/{mode} complete! You have access until 12 midnight (IST). "
                "After that you will start again from verification 1."
            )
        else:
            await m.reply(
                f"✅ Verification {t['stage']}/{mode} complete! You have access for {fmt_time(gap)}, "
                f"and then verification {t['stage'] + 1} will be required."
                + (" Please finish it before 12 midnight (IST), otherwise you will start again from verification 1."
                   if reset else "")
            )
    else:
        await m.reply(f"✅ Verified! You now have access for {fmt_time(db.get('verify_expire'))}.")
    if t["payload"]:
        await deliver(client, m, t["payload"])


@Client.on_message(filters.command("start") & filters.private)
async def start(client, m):
    uid = m.from_user.id
    if await db.add_user(uid):  # sirf pehli baar -> #NewUser log
        u = m.from_user
        name = " ".join(filter(None, [u.first_name, u.last_name])) or "—"
        total = await db.users.count_documents({})
        asyncio.create_task(log_event(
            client,
            f"#NewUser\n\n🆔 ID: <code>{u.id}</code>\n📛 Name: {html.escape(name)}\n"
            f"🔗 Username: {'@' + u.username if u.username else '—'}\n👤 Profile: {u.mention}\n"
            f"📅 Joined: {now_ist()}\n👥 Total Users: <b>{total}</b>",
        ))
    payload = m.command[1] if len(m.command) > 1 else None
    if not payload:
        return await welcome(client, m)
    if payload.startswith("verify_"):
        return await handle_verify(client, m, payload[7:])

    free_left = None
    if not await db.is_admin(uid):
        prem = await db.is_premium(uid)
        if not (prem and db.get("premium_skip_fsub")):
            missing = await not_joined(client, uid)
            if missing:
                return await m.reply(
                    fill(db.get("fsub_text"), m.from_user),
                    reply_markup=fsub_markup(client, missing, payload),
                )
        if not (prem and db.get("premium_skip_cooldown")):
            left = await cooldown_left(uid)  # checked before the free-link counter is touched
            if left:
                return await m.reply(
                    fill(db.get("cooldown_text"), m.from_user, time=fmt_time(left)),
                    reply_markup=Markup(
                        [[Btn("🔄 Try Again", url=f"https://t.me/{client.me.username}?start={payload}")]]
                    ),
                )
        if not (prem and db.get("premium_skip_verify")):
            stage = await next_stage(uid)
            if stage:
                free = int(db.get("free_limit") or 0)
                used = await db.free_used(uid) if (stage == 1 and free > 0) else 0
                if stage == 1 and used < free:  # still inside the free links
                    await db.bump_free(uid)
                    free_left = free - used - 1
                else:
                    return await send_verify(client, m, stage, payload)
    await deliver(client, m, payload)
    if free_left is not None and db.get("free_notice"):
        await m.reply(f"🎁 Free links left before verification: <b>{free_left}</b>")


@Client.on_callback_query(filters.regex("^dl_cancel$"))
async def dl_cancel(client, q):
    CANCEL.add(q.from_user.id)
    await q.answer("Cancelling the delivery...")


@Client.on_callback_query(filters.regex("^home$"))
async def home_cb(client, q):
    text, kb = await welcome_parts(q.from_user)
    await q.answer()
    msg, link = q.message, welcome_link()
    if link and not (getattr(msg, "photo", None) or getattr(msg, "video", None) or getattr(msg, "document", None)):
        try:  # bring the preview card back when the user comes back from Features / About
            return await _with_preview(lambda body, **kw: msg.edit_text(body, **kw), _card_body(text, link), kb, link)
        except Exception as e:
            log.info("home card edit skipped: %s", e)
    await edit_msg(msg, text, kb)


# ---------------- Features / About panels ----------------
def _pkg_version(*names):
    import importlib.metadata as md

    for n in names:
        try:
            return n, md.version(n)
        except Exception:
            continue
    return None, ""


LIB_NAMES = {"kurigram": "Kurigram", "pyrofork": "Pyrofork", "pyrotgfork": "PyroTGFork", "pyrogram": "Pyrogram"}


def about_text(client):
    dist, ver = _pkg_version("kurigram", "pyrofork", "pyrotgfork", "pyrogram")
    if not dist:
        dist, ver = "pyrogram", getattr(pyrogram, "__version__", "")
    _, motor_v = _pkg_version("motor")
    name = html.escape((db.get("developer_name") or "Bot Admin").strip())
    lines = [
        "ℹ️ <b>About this bot</b>",
        "",
        f"🤖 Bot: @{client.me.username}",
        f"🏷 Version: <b>{html.escape(BOT_VERSION)}</b>",
        "📚 Library: <b>" + f"{LIB_NAMES.get(dist, dist)} {ver}".strip() + "</b>" + (" (Pyrogram fork)" if dist != "pyrogram" else ""),
        f"🐍 Language: <b>Python {platform.python_version()}</b>",
        "🗄 Database: <b>MongoDB</b>" + (f" (Motor {motor_v})" if motor_v else ""),
        f"👨‍💻 Developer: <b>{name}</b>",
    ]
    extra = (db.get("about_extra") or "").strip()
    if extra:
        lines += ["", extra]
    return "\n".join(lines)


def developer_url():
    link = (db.get("developer_link") or "").strip()
    if link.startswith("@"):
        link = f"https://t.me/{link[1:]}"
    return link if link.startswith("http") else None


async def _show_panel(q, text, kb):
    """Edits the welcome message (text or photo caption); if Telegram refuses (e.g. caption too long), sends a new message."""
    try:
        await edit_msg(q.message, text, kb)
    except Exception:
        await q.message.reply(text, reply_markup=kb, disable_web_page_preview=True)


@Client.on_callback_query(filters.regex("^features$"))
async def features_cb(client, q):
    await q.answer()
    kb = Markup([[Btn("💎 Premium Plans", callback_data="plans")], [Btn("⬅️ Back", callback_data="home")]])
    await _show_panel(q, db.get("features_text"), kb)


@Client.on_callback_query(filters.regex("^about$"))
async def about_cb(client, q):
    await q.answer()
    rows = []
    url = developer_url()
    if url:
        rows.append([Btn("👨‍💻 Developer", url=url)])
    rows.append([Btn("⬅️ Back", callback_data="home")])
    await _show_panel(q, about_text(client), Markup(rows))
