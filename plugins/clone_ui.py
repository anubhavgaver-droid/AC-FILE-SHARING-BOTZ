"""Clone requests (main bot only): /clone for users, accept / reject for admins, /clones to manage."""
import html
import logging
import re
import secrets
import time

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton as Btn
from pyrogram.types import InlineKeyboardMarkup as Markup

import clonemgr
from database import BOTS, MAIN_DB, db
from helpers import STATE, admin_f, edit_msg

log = logging.getLogger("clone_ui")
TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")
PM = filters.private


async def _problem(uid, bot_id=None):
    """Why this user cannot request a clone right now ('' = fine)."""
    if not db.get("clone_enabled"):
        return "❌ Cloning is turned off right now."
    mine = [d async for d in MAIN_DB.clones.find({"owner": uid})]
    if len(mine) >= int(db.get("clone_max_per_user") or 1):
        return f"❌ You already have a clone: @{mine[0].get('username', '')}."
    if await MAIN_DB.clone_requests.find_one({"uid": uid, "status": "pending"}):
        return "⏳ Your earlier request is still waiting for the admin."
    if await MAIN_DB.clones.count_documents({}) >= int(db.get("clone_max_total") or 0):
        return "❌ There is no free slot for a new clone right now."
    if bot_id is not None and (
        await MAIN_DB.clones.find_one({"_id": bot_id})
        or await MAIN_DB.clone_requests.find_one({"bot_id": bot_id, "status": "pending"})
    ):
        return "❌ That bot is already connected or waiting for approval."
    return ""


async def _admin_targets():
    targets = {MAIN_DB.owner_id}
    async for a in MAIN_DB.admins.find({}):
        targets.add(a["_id"])
    targets.discard(0)
    return targets


@Client.on_message(filters.command("clone") & PM)
async def clone_cmd(client, m):
    if not db.is_main:
        return
    uid = m.from_user.id
    why = await _problem(uid)
    if why:
        return await m.reply(why)
    STATE[uid] = {"mode": "clone_token"}
    await m.reply(
        "🧬 <b>Create your own bot</b>\n\n"
        "1. Open @BotFather and send <code>/newbot</code>\n"
        "2. Choose a name and a username, then copy the <b>token</b> it gives you\n"
        "3. Send that token here\n\n"
        "I delete your message with the token right away. The admin must approve your request first.",
        reply_markup=Markup([[Btn("❌ Cancel", callback_data="clone_cancel")]]),
    )


@Client.on_callback_query(filters.regex("^clone_cancel$"))
async def clone_cancel(client, q):
    if (STATE.get(q.from_user.id) or {}).get("mode") == "clone_token":
        STATE.pop(q.from_user.id, None)
    await q.answer("Cancelled.")


@Client.on_message(PM & filters.text, group=5)
async def clone_token_input(client, m):
    if not db.is_main:
        return
    uid = m.from_user.id
    st = STATE.get(uid)
    text = (m.text or "").strip()
    if not st or st.get("mode") != "clone_token" or text.startswith("/"):
        return
    try:
        await m.delete()  # never leave a bot token lying in the chat
    except Exception:
        pass
    if not TOKEN_RE.match(text):
        return await client.send_message(uid, "❌ That does not look like a bot token. Send the token from @BotFather, or /cancel.")
    info = await clonemgr.tg_get_me(text)
    if not info:
        return await client.send_message(uid, "❌ Telegram did not accept this token. Check it and send it again, or /cancel.")
    bot_id = info["id"]
    if bot_id == client.me.id:
        return await client.send_message(uid, "❌ That is the token of this bot. Send the token of your own new bot.")
    why = await _problem(uid, bot_id)
    if why:
        STATE.pop(uid, None)
        return await client.send_message(uid, why)
    rid = secrets.token_hex(4)
    u = m.from_user
    caption = (
        f"🧬 <b>Clone request</b> #{rid}\n\n👤 {u.mention} (<code>{uid}</code>)\n"
        f"🔗 {'@' + u.username if u.username else '—'}\n"
        f"🤖 Bot: @{html.escape(info.get('username', ''))} (<code>{bot_id}</code>)"
    )
    kb = Markup([[Btn("✅ Accept", callback_data=f"cloneok_{rid}"), Btn("❌ Reject", callback_data=f"cloneno_{rid}")]])
    sent_to = []
    for target in await _admin_targets():
        try:
            c = await client.send_message(target, caption, reply_markup=kb)
            sent_to.append([target, c.id])
        except Exception as e:
            log.info("clone request not delivered to %s: %s", target, e)
    if not sent_to:
        STATE.pop(uid, None)
        return await client.send_message(uid, "❌ Could not reach the admin right now. Please try again later.")
    await MAIN_DB.clone_requests.insert_one({
        "_id": rid, "uid": uid, "bot_id": bot_id, "username": info.get("username", ""),
        "token_enc": clonemgr.encrypt(text), "status": "pending", "at": time.time(),
        "msgs": sent_to, "caption": caption,
    })
    STATE.pop(uid, None)
    await client.send_message(uid, "✅ Request sent. You will get a message as soon as the admin decides.")


@Client.on_callback_query(filters.regex(r"^clone(ok|no)_") & admin_f)
async def clone_decide(client, q):
    if not db.is_main:
        return
    approve = q.data.startswith("cloneok_")
    rid = q.data.split("_", 1)[1]
    pending = await MAIN_DB.clone_requests.find_one({"_id": rid, "status": "pending"})
    if not pending:
        return await q.answer("Already handled by another admin.", show_alert=True)
    if approve and await MAIN_DB.clones.count_documents({}) >= int(db.get("clone_max_total") or 0):
        return await q.answer("No free slot. Raise 'Max Clones on this Server' first or remove a clone.", show_alert=True)
    doc = await MAIN_DB.clone_requests.find_one_and_update(
        {"_id": rid, "status": "pending"},
        {"$set": {"status": "approved" if approve else "rejected", "by": q.from_user.id}},
    )
    if not doc:
        return await q.answer("Already handled by another admin.", show_alert=True)
    if approve:
        entry = {"owner": doc["uid"], "username": doc["username"], "token_enc": doc["token_enc"],
                 "status": "active", "at": time.time(), "request": rid}
        await MAIN_DB.clones.update_one({"_id": doc["bot_id"]}, {"$set": entry}, upsert=True)
        try:
            await clonemgr.start_clone({"_id": doc["bot_id"], **entry})
        except Exception as e:
            await MAIN_DB.clones.update_one(
                {"_id": doc["bot_id"]}, {"$set": {"status": "error", "error": str(e)[:200]}}
            )
            verdict = f"⚠️ Approved by {q.from_user.mention}, but the bot could not start:\n<code>{html.escape(str(e))[:200]}</code>"
            user_msg = "⚠️ Your request was approved, but your bot could not be started. The admin has been told."
        else:
            verdict = f"✅ Accepted by {q.from_user.mention}"
            user_msg = (
                f"🎉 <b>Your bot @{html.escape(doc['username'])} is live!</b>\n\n"
                "Open it and send /start. Use /settings there to set it up: first connect your database "
                "channel with /setdb (add the bot as admin in that channel)."
            )
    else:
        verdict = f"❌ Rejected by {q.from_user.mention}"
        user_msg = "❌ <b>Your clone request was rejected.</b>\nIf you think this is a mistake, please contact the admin."
    try:
        await client.send_message(doc["uid"], user_msg)
    except Exception as e:
        log.info("could not notify %s: %s", doc["uid"], e)
    await q.answer("Done")
    for chat, mid in doc.get("msgs", []):
        try:
            await client.edit_message_text(chat, mid, f"{doc.get('caption', '')}\n\n{verdict}")
        except Exception:
            pass


# ---------------- /clones (admins of the main bot) ----------------
async def _clones_view():
    docs = [d async for d in MAIN_DB.clones.find({})]
    pending = await MAIN_DB.clone_requests.count_documents({"status": "pending"})
    lines = [
        "🧬 <b>Clone bots</b>",
        f"Feature: <b>{'ON' if db.get('clone_enabled') else 'OFF'}</b>   "
        f"Running: <b>{sum(1 for d in docs if d['_id'] in BOTS)}</b>   Pending requests: <b>{pending}</b>",
        "",
    ]
    rows = []
    for d in docs:
        running = d["_id"] in BOTS
        state = "✅ running" if running else ("❌ error" if d.get("status") == "error" else "⏸ stopped")
        lines.append(f"• @{html.escape(d.get('username', ''))} — owner <code>{d['owner']}</code> — {state}")
        rows.append([
            Btn("⏸ Stop" if running else "▶️ Start", callback_data=f"cln_{'stop' if running else 'start'}_{d['_id']}"),
            Btn("🗑 Remove", callback_data=f"cln_del_{d['_id']}"),
        ])
    if not docs:
        lines.append("No clones yet.")
    return "\n".join(lines), (Markup(rows) if rows else None)


@Client.on_message(filters.command("clones") & PM & admin_f)
async def clones_cmd(client, m):
    if not db.is_main:
        return
    text, kb = await _clones_view()
    await m.reply(text, reply_markup=kb)


@Client.on_callback_query(filters.regex(r"^cln_(stop|start|del)_\d+$") & admin_f)
async def clone_manage(client, q):
    if not db.is_main:
        return
    _, action, sid = q.data.split("_")
    bot_id = int(sid)
    doc = await MAIN_DB.clones.find_one({"_id": bot_id})
    if not doc:
        return await q.answer("Clone not found.", show_alert=True)
    if action == "stop":
        await clonemgr.stop_clone(bot_id)
        await MAIN_DB.clones.update_one({"_id": bot_id}, {"$set": {"status": "stopped"}})
    elif action == "start":
        try:
            await clonemgr.start_clone(doc)
            await MAIN_DB.clones.update_one({"_id": bot_id}, {"$set": {"status": "active"}})
        except Exception as e:
            await MAIN_DB.clones.update_one({"_id": bot_id}, {"$set": {"status": "error", "error": str(e)[:200]}})
            await q.answer(f"Could not start: {str(e)[:150]}", show_alert=True)
    else:
        await clonemgr.stop_clone(bot_id)
        await MAIN_DB.clones.delete_one({"_id": bot_id})
        try:
            await client.send_message(doc["owner"], f"ℹ️ Your clone @{doc.get('username', '')} was removed by the admin.")
        except Exception:
            pass
    await q.answer("Done")
    text, kb = await _clones_view()
    await edit_msg(q.message, text, kb)
