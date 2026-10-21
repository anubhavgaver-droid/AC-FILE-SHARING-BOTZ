import secrets

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton as Btn
from pyrogram.types import InlineKeyboardMarkup as Markup

from database import db
from helpers import STATE, admin_f, build_link, is_bot_admin, parse_ref

PM = filters.private & admin_f

STOP_KB = Markup([[Btn("🛑 Stop & Get Link", callback_data="cb_stop")]])


def share_kb(link):
    return Markup([[Btn("🔁 Share", url=f"https://t.me/share/url?url={link}")]])


@Client.on_message(filters.command("cancel") & PM)
async def cancel(client, m):
    STATE.pop(m.from_user.id, None)
    await m.reply(
        "❌ Cancelled.",
        reply_markup=Markup([[Btn("⬅️ Back", callback_data="pg_main"), Btn("🏠 Home", callback_data="home")]]),
    )


# ---------------- /single ----------------
@Client.on_message(filters.command(["genlink", "single"]) & PM)
async def single(client, m):
    if not db.get("db_channel"):
        return await m.reply("⚠️ Please set the DB channel first: <code>/setdb -100xxxxxxxxxx</code>")
    STATE[m.from_user.id] = {"mode": "single"}
    await m.reply(
        "📤 Send anything: file, video, audio, photo, voice, sticker, text, poll... (forwarded or direct).\n"
        "Each message gets its own link.\n"
        "To stop, send /cancel"
    )


# ---------------- /custom_batch ----------------
@Client.on_message(filters.command("custom_batch") & PM)
async def custom_batch(client, m):
    if not db.get("db_channel"):
        return await m.reply("⚠️ Please set the DB channel first: <code>/setdb -100xxxxxxxxxx</code>")
    STATE[m.from_user.id] = {"mode": "custom", "ids": [], "status": None}
    await m.reply(
        "📦 Send files, videos, audio, text, photos — anything, one by one. When you are done, tap the <b>Stop</b> button below.",
        reply_markup=STOP_KB,
    )


@Client.on_callback_query(filters.regex("^cb_stop$") & admin_f)
async def stop_custom(client, q):
    st = STATE.get(q.from_user.id)
    if not st or st.get("mode") != "custom":
        return await q.answer("There is no active custom batch.", show_alert=True)
    if not st["ids"]:
        return await q.answer("You have not sent anything yet.", show_alert=True)
    STATE.pop(q.from_user.id)
    key = secrets.token_urlsafe(6)
    await db.batches.insert_one({"_id": key, "chat_id": int(db.get("db_channel")), "ids": st["ids"]})
    link = await build_link(client, f"c_{key}")
    await q.message.edit_text(
        f"✅ <b>Custom batch ready</b> ({len(st['ids'])} files)\n\n<code>{link}</code>",
        reply_markup=share_kb(link),
        disable_web_page_preview=True,
    )


# ---------------- /batch ----------------
@Client.on_message(filters.command("batch") & PM)
async def batch(client, m):
    STATE[m.from_user.id] = {"mode": "batch1"}
    await m.reply(
        "1️⃣ Forward the <b>FIRST</b> message from the channel (or send its post link).\n"
        "⚠️ The bot must be an admin in that channel.\n/cancel to abort"
    )


# ---------------- common flow handler ----------------
@Client.on_message(PM, group=1)
async def flow(client, m):
    uid = m.from_user.id
    st = STATE.get(uid)
    if not st or (m.text and m.text.startswith("/")):
        return
    mode = st["mode"]

    if mode in ("single", "custom"):
        chan = int(db.get("db_channel"))
        try:
            copied = await m.copy(chan)
        except Exception as e:
            return await m.reply(f"❌ Could not save to the DB channel: <code>{e}</code>")
        if mode == "single":
            link = await build_link(client, f"s_{chan}_{copied.id}")
            return await m.reply(f"✅ <code>{link}</code>", reply_markup=share_kb(link), quote=True,
                                 disable_web_page_preview=True)
        st["ids"].append(copied.id)
        if st.get("status"):
            try:
                await st["status"].delete()
            except Exception:
                pass
        st["status"] = await m.reply(
            f"✅ Added: <b>{len(st['ids'])}</b> item(s)\nSend more or tap Stop.",
            reply_markup=STOP_KB,
            quote=True,
        )
        return

    if mode in ("batch1", "batch2"):
        try:
            ref = await parse_ref(client, m)
        except Exception:
            ref = None
        if not ref:
            return await m.reply("❌ Send a message forwarded from a channel, or a t.me post link.")
        chat_id, msg_id = ref
        if not await is_bot_admin(client, chat_id):
            return await m.reply("❌ The bot is not an admin in that channel. Make it an admin and send it again.")
        if mode == "batch1":
            st.update(mode="batch2", chat=chat_id, first=msg_id)
            return await m.reply("2️⃣ Now forward the <b>LAST</b> message (or send its link).")
        if chat_id != st["chat"]:
            return await m.reply("❌ The last message must come from the same channel as the first.")
        STATE.pop(uid)
        first, last = sorted((st["first"], msg_id))
        link = await build_link(client, f"b_{chat_id}_{first}_{last}")
        await m.reply(
            f"✅ <b>Batch ready</b> ({last - first + 1} messages)\n\n<code>{link}</code>",
            reply_markup=share_kb(link),
            disable_web_page_preview=True,
        )
