import re
import time
from datetime import datetime, timedelta, timezone

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton as Btn
from pyrogram.types import InlineKeyboardMarkup as Markup

from database import db
from helpers import admin_f, fmt_time

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
    await m.reply(db.get("plans_text"), reply_markup=buy_markup(), disable_web_page_preview=True)


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
        return await m.reply("❌ You do not have premium. See /plans.", reply_markup=buy_markup())
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
