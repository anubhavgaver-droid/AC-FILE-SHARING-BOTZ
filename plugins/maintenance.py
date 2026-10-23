from pyrogram import Client, StopPropagation, filters

from database import db
from helpers import admin_f


async def _on(_, __, ___):
    return bool(db.get("maintenance"))


maint_f = filters.create(_on)


# group=-1 runs before every other handler: normal users only see the maintenance notice,
# admins and the owner keep working as usual.
@Client.on_message(filters.private & maint_f & ~admin_f, group=-1)
async def maintenance_message(client, m):
    await m.reply(db.get("maintenance_text"), disable_web_page_preview=True)
    raise StopPropagation


@Client.on_callback_query(maint_f & ~admin_f, group=-1)
async def maintenance_callback(client, q):
    await q.answer("🛠 The bot is under maintenance. Please try again later.", show_alert=True)
    raise StopPropagation
