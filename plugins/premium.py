import html
import logging
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton as Btn
from pyrogram.types import InlineKeyboardMarkup as Markup

from config import OWNER_ID
from database import db
from helpers import STATE, admin_f, fmt_time
from smallcaps import sc

log = logging.getLogger("premium")

PM = filters.private & admin_f
IST = timezone(timedelta(hours=5, minutes=30))
UNITS = {"h": 3600, "d": 86400, "w": 604800, "m": 2592000, "y": 31536000}


def parse_duration(s):
    r = re.fullmatch(r"(\d+)([hdwmy]?)", s.lower())
    return int(r.group(1)) * UNITS[r.group(2) or "d"] if r else None


def fmt_date(ts):
    return datetime.fromtimestamp(ts, IST).strftime("%d %b %Y, %I:%M %p IST")


def buy_markup():
    c = (db.get("premium_contact") or "").strip()
    if c.startswith("@"):
        c = f"https://t.me/{c[1:]}"
    return Markup([[Btn("💳 Buy Premium", url=c)]]) if c.startswith("http") else None


async def send_plans(m):
    await m.reply(db.get("plans_text"), reply_markup=plans_markup(), disable_web_page_preview=True)


@Client.on_message(filters.command("plans") & filters.private)
async def plans(client, m):
    await send_plans(m)


@Client.on_callback_query(filters.regex("^plans$"))
async def plans_cb(client, q):
    await q.answer()
    await send_plans(q.message)


@Client.on_message(filters.command("myplan") & filters.private)
async def myplan(client, m):
    until = await db.premium_until(m.from_user.id)
    if not until:
        return await m.reply("❌ You do not have premium. See /plans.", reply_markup=plans_markup())
    await m.reply(
        f"💎 <b>Premium active</b>\n\n⏳ Time left: <b>{fmt_time(until - time.time())}</b>\n"
        f"📅 Expires: <b>{fmt_date(until)}</b>"
    )


@Client.on_message(filters.command("addpremium") & PM)
async def addpremium(client, m):
    if len(m.command) < 3 or not m.command[1].isdigit() or not parse_duration(m.command[2]):
        return await m.reply(
            "Use: <code>/addpremium user_id 7d</code>\nUnits: h=hours, d=days, w=weeks, m=month(30d), y=year"
        )
    uid, secs = int(m.command[1]), parse_duration(m.command[2])
    until = await db.add_premium(uid, secs)
    await m.reply(f"✅ <code>{uid}</code> premium till <b>{fmt_date(until)}</b>")
    try:
        await client.send_message(uid, f"🎉 <b>Premium activated!</b>\n📅 Expires: <b>{fmt_date(until)}</b>")
    except Exception:
        pass


@Client.on_message(filters.command("removepremium") & PM)
async def removepremium(client, m):
    if len(m.command) < 2 or not m.command[1].isdigit():
        return await m.reply("Use: <code>/removepremium user_id</code>")
    ok = await db.remove_premium(int(m.command[1]))
    await m.reply("✅ Premium removed." if ok else "❌ This user is not in the premium list.")


@Client.on_message(filters.command("premiums") & PM)
async def premiums(client, m):
    lines = []
    async for p in db.premium.find({"until": {"$gt": time.time()}}).limit(50):
        lines.append(f"• <code>{p['_id']}</code> — {fmt_date(p['until'])}")
    await m.reply("💎 <b>Premium users</b>\n\n" + ("\n".join(lines) or "No active premium users."))


# ---------------- plans + payment screenshot ----------------
def parse_plans():
    """Lines of the 'Plans List' setting: 'Label | 7d | ₹49'  ->  [(label, seconds, price)]."""
    plans = []
    for line in (db.get("plans_list") or "").splitlines():
        parts = [x.strip() for x in line.split("|")]
        if len(parts) >= 3 and parts[0] and parse_duration(parts[1]):
            plans.append((parts[0], parse_duration(parts[1]), parts[2]))
    return plans[:8]


def plans_markup():
    rows = [[Btn(f"💳 {label} — {price}", callback_data=f"buy_{i}")] for i, (label, _, price) in enumerate(parse_plans())]
    c = (db.get("premium_contact") or "").strip()
    if c.startswith("@"):
        c = f"https://t.me/{c[1:]}"
    if c.startswith("http"):
        rows.append([Btn("💬 Contact", url=c)])
    return Markup(rows) if rows else None


@Client.on_callback_query(filters.regex(r"^buy_\d+$"))
async def buy_cb(client, q):
    plans = parse_plans()
    i = int(q.data[4:])
    if i >= len(plans):
        return await q.answer("This plan is no longer available.", show_alert=True)
    uid = q.from_user.id
    if await db.payments.find_one({"uid": uid, "status": "pending"}):
        return await q.answer("You already have a payment waiting for approval.", show_alert=True)
    label, _, price = plans[i]
    STATE[uid] = {"mode": "pay", "plan": i}
    text = (
        f"{db.get('pay_text')}\n\n📦 Plan: <b>{html.escape(label)}</b>\n💰 Amount: <b>{html.escape(price)}</b>\n\n"
        "📸 Now send the payment screenshot here.\n/cancel to stop."
    )
    kb = Markup([[Btn("❌ Cancel", callback_data="pay_cancel")]])
    await q.answer()
    photo = db.get("pay_photo")
    if photo:
        try:
            return await client.send_photo(q.message.chat.id, photo, caption=text, reply_markup=kb)
        except Exception as e:
            log.warning("pay_photo failed: %s", e)
    await client.send_message(q.message.chat.id, text, reply_markup=kb)


@Client.on_callback_query(filters.regex("^pay_cancel$"))
async def pay_cancel(client, q):
    if (STATE.get(q.from_user.id) or {}).get("mode") == "pay":
        STATE.pop(q.from_user.id, None)
    await q.answer("Cancelled.")


@Client.on_message(filters.command("cancel") & filters.private & ~admin_f)
async def user_cancel(client, m):
    if (STATE.get(m.from_user.id) or {}).get("mode") == "pay":
        STATE.pop(m.from_user.id, None)
        await m.reply("❌ Cancelled.")


@Client.on_message(filters.private & filters.text, group=3)
async def pay_text_hint(client, m):
    st = STATE.get(m.from_user.id)
    if st and st.get("mode") == "pay" and not m.text.startswith("/"):
        await m.reply("📸 Please send the payment screenshot as a photo, or /cancel.")


@Client.on_message(filters.private & (filters.photo | filters.document), group=3)
async def got_screenshot(client, m):
    uid = m.from_user.id
    st = STATE.get(uid)
    if not st or st.get("mode") != "pay":
        return
    plans = parse_plans()
    STATE.pop(uid, None)
    if st["plan"] >= len(plans):
        return await m.reply("❌ This plan is no longer available.")
    label, secs, price = plans[st["plan"]]
    rid = secrets.token_hex(4)
    u = m.from_user
    caption = (
        f"💳 <b>Payment request</b> #{rid}\n\n👤 {u.mention} (<code>{uid}</code>)\n"
        f"🔗 {'@' + u.username if u.username else '—'}\n"
        f"📦 Plan: <b>{html.escape(label)}</b>\n💰 Amount: <b>{html.escape(price)}</b>"
    )
    kb = Markup([[Btn("✅ Approve", callback_data=f"payok_{rid}"), Btn("❌ Reject", callback_data=f"payno_{rid}")]])
    targets = {OWNER_ID}
    async for a in db.admins.find({}):
        targets.add(a["_id"])
    sent_to = []
    for target in targets:
        if not target:
            continue
        try:
            c = await m.copy(target, caption=sc(caption), reply_markup=kb)
            sent_to.append([target, c.id])
        except Exception as e:
            log.warning("could not send the payment request to %s: %s", target, e)
    if not sent_to:
        return await m.reply("❌ Could not reach the admin right now. Please contact support.")
    await db.payments.insert_one({
        "_id": rid, "uid": uid, "label": label, "secs": secs, "price": price, "status": "pending",
        "at": time.time(), "msgs": sent_to, "caption": caption,
    })
    await m.reply("✅ Screenshot received. You will get a message as soon as the admin checks it.")


@Client.on_callback_query(filters.regex(r"^pay(ok|no)_") & admin_f)
async def pay_decide(client, q):
    approve = q.data.startswith("payok_")
    rid = q.data.split("_", 1)[1]
    doc = await db.payments.find_one_and_update(
        {"_id": rid, "status": "pending"},
        {"$set": {"status": "approved" if approve else "rejected", "by": q.from_user.id}},
    )
    if not doc:
        return await q.answer("Already handled by another admin.", show_alert=True)
    if approve:
        until = await db.add_premium(doc["uid"], doc["secs"])
        user_msg = f"🎉 <b>Payment approved!</b>\nPremium is active.\n📅 Expires: <b>{fmt_date(until)}</b>"
        verdict = f"✅ Approved by {q.from_user.mention}"
    else:
        user_msg = "❌ <b>Payment rejected.</b>\nIf you think this is a mistake, please contact support."
        verdict = f"❌ Rejected by {q.from_user.mention}"
    try:
        await client.send_message(doc["uid"], user_msg)
    except Exception as e:
        log.warning("could not notify user %s: %s", doc["uid"], e)
    await q.answer("Done")
    for chat, mid in doc.get("msgs", []):  # every admin copy loses its buttons and shows the result
        try:
            await client.edit_message_caption(chat, mid, f"{doc.get('caption', '')}\n\n{verdict}")
        except Exception:
            pass
