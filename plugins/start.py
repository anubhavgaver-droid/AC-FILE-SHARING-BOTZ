import asyncio
import html
import time

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton as Btn
from pyrogram.types import InlineKeyboardMarkup as Markup

from database import db
from helpers import (
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
)


async def welcome_parts(user):
    text = fill(db.get("welcome_text"), user)
    rows = parse_buttons(db.get("welcome_buttons"))
    rows.extend(sponsor_rows())
    rows.append([Btn("💎 Premium Plans", callback_data="plans")])
    if await db.is_admin(user.id):  # shown to admins/owner only
        rows.append([Btn("⚙️ Settings", callback_data="pg_main")])
    return text, Markup(rows)


async def welcome(client, m):
    text, kb = await welcome_parts(m.from_user)
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
    if t["stage"] < mode and gap <= 0 and db.get(f"v{t['stage'] + 1}_api_url"):
        return await send_verify(client, m, t["stage"] + 1, t["payload"])
    if t["stage"] < mode:
        await m.reply(
            f"✅ Verification {t['stage']}/{mode} complete! You have access for {fmt_time(gap)}, "
            f"and then verification {t['stage'] + 1} will be required."
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

    if not await db.is_admin(uid):
        prem = await db.is_premium(uid)
        if not (prem and db.get("premium_skip_fsub")):
            missing = await not_joined(client, uid)
            if missing:
                return await m.reply(
                    fill(db.get("fsub_text"), m.from_user),
                    reply_markup=fsub_markup(client, missing, payload),
                )
        if not (prem and db.get("premium_skip_verify")):
            stage = await next_stage(uid)
            if stage:
                return await send_verify(client, m, stage, payload)
    await deliver(client, m, payload)


@Client.on_callback_query(filters.regex("^dl_cancel$"))
async def dl_cancel(client, q):
    CANCEL.add(q.from_user.id)
    await q.answer("Cancelling the delivery...")


@Client.on_callback_query(filters.regex("^home$"))
async def home_cb(client, q):
    text, kb = await welcome_parts(q.from_user)
    await q.answer()
    await edit_msg(q.message, text, kb)
