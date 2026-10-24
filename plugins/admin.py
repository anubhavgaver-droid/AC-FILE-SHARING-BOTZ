import asyncio
import html
import os
import sys
import time

from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardButton as Btn
from pyrogram.types import InlineKeyboardMarkup as Markup

from config import DB_NAME, OWNER_ID
from database import DEFAULTS, db
from helpers import (
    STATE,
    admin_f,
    build_link,
    clear_admin_menu,
    describe_post,
    edit_msg as edit,
    fmt_time,
    fwd_info,
    is_bot_admin,
    log_event,
    parse_ref,
    set_admin_menu,
    shorten,
)

PM = filters.private & admin_f
owner_f = filters.user(OWNER_ID)

LABELS = {
    "welcome_text": "Welcome Text",
    "welcome_photo": "Welcome Photo",
    "welcome_buttons": "Welcome Buttons",
    "verify_mode": "Verify Mode",
    "verify_via_server": "Verify Flow",
    "shortener_alias": "Long Short-Link Alias",
    "alias_length": "Alias Length (min 15)",
    "v1_api_url": "Verify-1 API URL",
    "v1_api_key": "Verify-1 API Key",
    "v2_api_url": "Verify-2 API URL",
    "v2_api_key": "Verify-2 API Key",
    "verify_expire": "Verify Valid For",
    "verify_gap": "Gap 1st→2nd Verify",
    "verify_min_time": "Min Verify Time",
    "verify_tutorial": "Tutorial Link",
    "verify_text": "Verify Text",
    "protect_content": "Protect Content",
    "auto_delete": "Auto Delete",
    "auto_delete_text": "Auto-Delete Text",
    "wait_text": "Please-Wait Text",
    "fsub_text": "Force-Sub Text",
    "plans_text": "Plans Text",
    "plans_list": "Plans List (buttons)",
    "upi_id": "UPI ID",
    "join_enabled": "Channel Join Links",
    "join_expire": "Invite Valid For",
    "join_text": "Join Message",
    "premium_reminder": "Premium Expiry Reminder",
    "premium_remind_before": "Remind Before Expiry",
    "link_cooldown": "Link Cooldown",
    "cooldown_text": "Cooldown Message",
    "premium_skip_cooldown": "Premium skips Cooldown",
    "pay_text": "Payment Instructions",
    "pay_photo": "Payment QR Photo",
    "free_limit": "Free Links Before Verify",
    "free_notice": "Show Free-Links-Left Notice",
    "maintenance": "Maintenance Mode",
    "maintenance_text": "Maintenance Message",
    "mirror_channel": "Mirror Channel ID",
    "sponsor_label": "Sponsor Button Text",
    "sponsor_url": "Sponsor Channel Link",
    "log_channel": "Log Channel ID",
    "permalink_enabled": "Permanent Links (Website)",
    "permalink_bot": "Redirect Bot Username",
    "link_expire": "Link Expiry",
    "site_name": "Website Name",
    "site_tagline": "Website Tagline",
    "redirect_timer": "Redirect Timer",
    "stream_enabled": "Streaming (Premium)",
    "stream_expire": "Stream Link Valid",
    "stream_base_url": "Server Public URL",
    "premium_contact": "Buy Contact",
    "premium_skip_verify": "Premium skips Verify",
    "premium_skip_fsub": "Premium skips Force-Sub",
    "premium_no_autodelete": "Premium: No Auto-Delete",
}
PAGES = {
    "welcome": ("🖼 Welcome", ["welcome_text", "welcome_photo", "welcome_buttons"]),
    "verify": (
        "🔐 Verification",
        ["verify_mode", "verify_via_server", "shortener_alias", "alias_length", "v1_api_url", "v1_api_key", "v2_api_url", "v2_api_key",
         "verify_expire", "verify_gap", "verify_min_time", "verify_tutorial", "verify_text"],
    ),
    "files": ("🗑 Files", ["protect_content", "auto_delete", "auto_delete_text", "wait_text"]),
    "fsub": ("📢 Force-Sub", ["fsub_text"]),
    "sponsor": ("🤝 Sponsor", ["sponsor_label", "sponsor_url"]),
    "logs": ("📝 Log Channel", ["log_channel"]),
    "website": ("🌐 Website", ["permalink_enabled", "permalink_bot", "link_expire", "redirect_timer", "site_name", "site_tagline"]),
    "stream": ("🎬 Streaming", ["stream_enabled", "stream_expire", "stream_base_url"]),
    "free": ("🎁 Free Limit", ["free_limit", "free_notice"]),
    "joinch": ("📡 Channel Links", ["join_enabled", "join_expire", "join_text"]),
    "cooldown": ("⏱ Cooldown", ["link_cooldown", "cooldown_text", "premium_skip_cooldown"]),
    "maint": ("🛠 Maintenance", ["maintenance", "maintenance_text"]),
    "mirror": ("🪞 Mirror Channel", ["mirror_channel"]),
    "premium": (
        "💎 Premium",
        ["plans_text", "plans_list", "upi_id", "pay_text", "pay_photo", "premium_contact", "premium_skip_verify", "premium_skip_fsub",
         "premium_no_autodelete", "premium_reminder", "premium_remind_before"],
    ),
}
BOOL = {"join_enabled", "premium_reminder", "premium_skip_cooldown", "free_notice", "maintenance", "shortener_alias", "permalink_enabled", "stream_enabled", "protect_content", "premium_skip_verify", "premium_skip_fsub", "premium_no_autodelete"}
NUM = {"join_expire", "link_cooldown", "premium_remind_before", "free_limit", "alias_length", "redirect_timer", "link_expire", "stream_expire", "auto_delete", "verify_expire", "verify_gap", "verify_min_time"}
RAW = {"welcome_photo", "welcome_buttons", "v1_api_url", "v1_api_key", "v2_api_url", "v2_api_key",
       "verify_tutorial", "premium_contact", "sponsor_label", "sponsor_url", "stream_base_url", "permalink_bot", "site_name", "site_tagline", "plans_list", "pay_photo", "upi_id"}


def show(key):
    v = db.get(key)
    if key in BOOL:
        return "✅" if v else "❌"
    if key == "verify_mode":
        return {0: "Off", 1: "1 step", 2: "2 steps"}[int(v)]
    if key == "verify_via_server":
        return {0: "Direct", 1: "Server first", 2: "Shortener first"}[int(v or 0)]
    if key == "link_expire":
        return fmt_time(v) if v else "Never"
    if key == "redirect_timer":
        return f"{int(v)}s" if v else "Instant"
    if key == "free_limit":
        return f"{int(v)} link(s)" if v else "Off (verify at once)"
    if key == "alias_length":
        return f"{max(15, min(30, int(v or 15)))} chars"
    if key in NUM:
        return fmt_time(v) if v else "Off"
    return "✔️" if v else "—"


def main_kb():
    rows = [[Btn(t, callback_data=f"pg_{k}")] for k, (t, _) in PAGES.items()]
    rows.append([Btn("⬅️ Back", callback_data="home")])
    return Markup(rows)


async def page_kb(page):
    rows = [[Btn(f"{LABELS[k]}: {show(k)}", callback_data=f"k_{k}")] for k in PAGES[page][1]]
    if page == "fsub":
        rows.append([Btn("➕ Add Channel", callback_data="fs_add")])
        async for c in db.fsub.find({}):
            rows.append([Btn(f"🗑 {c['title']} ({c['mode']})", callback_data=f"fs_del_{c['chat_id']}")])
    if page == "joinch":
        rows.append([Btn("➕ Connect Channel", callback_data="jc_add")])
        async for c in db.channels.find({}):
            rows.append([Btn(f"🗑 {c['title']}", callback_data=f"jc_del_{c['_id']}")])
    rows.append([Btn("⬅️ Back", callback_data="pg_main")])
    return Markup(rows)


def page_of(key):
    return next(p for p, (_, ks) in PAGES.items() if key in ks)


@Client.on_message(filters.command("settings") & PM)
async def settings(client, m):
    await m.reply("⚙️ <b>Bot Settings</b>", reply_markup=main_kb())


@Client.on_callback_query(filters.regex(r"^(pg|k)_") & admin_f)
async def settings_cb(client, q):
    d = q.data
    if d.startswith("pg_") and (STATE.get(q.from_user.id) or {}).get("mode") in ("set", "fsadd", "fsadd2"):
        STATE.pop(q.from_user.id, None)  # Back dabane par pending input cancel
    if d == "pg_main":
        return await edit(q.message, "⚙️ <b>Bot Settings</b>", main_kb())
    if d.startswith("pg_"):
        page = d[3:]
        hint = {
            "fsub": "\n\nTap a 🗑 button to remove that channel",
            "free": "\n\nHow many links a new user can open before verification starts. 0 = verify at once.",
            "mirror": "\n\nEvery file saved with /genlink and /custom_batch is also copied here. If the main DB channel "
                      "is lost, links keep working from this channel. Use /setmirror to set it.",
            "cooldown": "\n\nSeconds a user must wait after opening a link before opening the next one. 0 = off. Admins are never limited.",
        "joinch": "\n\nConnect private channels, then make one-time join links with /chanlink. Tap a 🗑 button to disconnect a channel.",
        "maint": "\n\nWhen ON, normal users only see the maintenance message. Admins keep working.",
        }.get(page, "")
        return await edit(q.message, f"{PAGES[page][0]} settings{hint}", await page_kb(page))
    key = d[2:]
    if key in BOOL:
        await db.set(key, not db.get(key))
    elif key in ("verify_mode", "verify_via_server"):
        await db.set(key, (int(db.get(key) or 0) + 1) % 3)
    else:
        cur = str(db.get(key))
        if "key" in key and cur:
            cur = cur[:4] + "…"
        STATE[q.from_user.id] = {"mode": "set", "key": key, "msg": q.message}
        placeholders = "\n\nPlaceholders: <code>{mention} {first} {time} {stage} {mode}</code>" \
            if key.endswith("_text") else ""
        return await edit(
            q.message,
            f"✏️ <b>{LABELS[key]}</b>: send the new value.\n\nCurrent: <code>{html.escape(cur)[:300]}</code>"
            f"{placeholders}\n\n/default = reset, /cancel = abort",
            Markup([[Btn("⬅️ Back", callback_data=f"pg_{page_of(key)}")]]),
        )
    await q.message.edit_reply_markup(await page_kb(page_of(key)))


@Client.on_message(PM, group=2)
async def set_value(client, m):
    st = STATE.get(m.from_user.id)
    if st and st.get("mode") == "fsadd":
        return await fsadd_input(client, m)
    if st and st.get("mode") == "jcadd":
        return await jcadd_input(client, m)
    if not st or st.get("mode") != "set":
        return
    key = st["key"]
    txt = (m.text or "").strip()
    if txt.startswith("/") and txt.lower() != "/default":
        return
    if txt.lower() == "/default":
        val = DEFAULTS[key]
    elif key in ("welcome_photo", "pay_photo") and m.photo:
        val = m.photo.file_id
    elif not m.text:
        return await m.reply("📝 Please send text.")
    elif key in ("log_channel", "mirror_channel"):
        if not txt.lstrip("-").isdigit() or not await is_bot_admin(client, int(txt)):
            return await m.reply("❌ Send a valid channel ID (-100...) and make the bot an admin in that channel.")
        val = int(txt)
    elif key in NUM:
        if not txt.isdigit():
            return await m.reply("🔢 Please send a number (seconds, or a count for the free limit).")
        val = int(txt)
    elif key in RAW:
        val = txt.lstrip("@") if key == "permalink_bot" else txt
    else:
        val = m.text.html
    STATE.pop(m.from_user.id)
    await db.set(key, val)
    await m.reply("✅ Saved.", reply_markup=Markup([[Btn("⬅️ Settings", callback_data=f"pg_{page_of(key)}")]]))


# ---------------- DB channel ----------------
@Client.on_message(filters.command("setdb") & PM)
async def setdb(client, m):
    if len(m.command) < 2 or not m.command[1].lstrip("-").isdigit():
        return await m.reply("Use: <code>/setdb -100xxxxxxxxxx</code>")
    cid = int(m.command[1])
    if not await is_bot_admin(client, cid):
        return await m.reply("❌ The bot is not an admin in that channel.")
    await db.set("db_channel", cid)
    await m.reply(f"✅ DB channel set: <code>{cid}</code>")


# ---------------- force subscribe ----------------
@Client.on_message(filters.command("addfsub") & PM)
async def addfsub(client, m):
    if len(m.command) < 3 or m.command[2] not in ("public", "private", "request"):
        return await m.reply("Use: <code>/addfsub -100xxxxxxxxxx public|private|request</code>")
    cid, mode = int(m.command[1]), m.command[2]
    try:
        chat = await client.get_chat(cid)
        if mode == "public" and chat.username:
            link = f"https://t.me/{chat.username}"
        elif mode == "request":
            link = (await client.create_chat_invite_link(cid, creates_join_request=True)).invite_link
        else:
            link = (await client.create_chat_invite_link(cid)).invite_link
    except Exception as e:
        return await m.reply(f"❌ Make the bot an admin with the invite-users permission.\n<code>{e}</code>")
    await db.fsub.update_one(
        {"chat_id": cid}, {"$set": {"chat_id": cid, "mode": mode, "link": link, "title": chat.title}},
        upsert=True,
    )
    await m.reply(f"✅ Added <b>{chat.title}</b> ({mode})")


@Client.on_message(filters.command("delfsub") & PM)
async def delfsub(client, m):
    if len(m.command) < 2:
        return await m.reply("Use: <code>/delfsub -100xxxxxxxxxx</code>")
    r = await db.fsub.delete_one({"chat_id": int(m.command[1])})
    await m.reply("✅ Removed." if r.deleted_count else "❌ Not found.")


@Client.on_message(filters.command("fsubs") & PM)
async def fsubs(client, m):
    lines = [f"• <b>{c['title']}</b> — <code>{c['chat_id']}</code> ({c['mode']})" async for c in db.fsub.find({})]
    await m.reply("\n".join(lines) or "No force-sub channels yet.")


@Client.on_chat_join_request()
async def join_request(client, r):
    if await db.fsub.find_one({"chat_id": r.chat.id}):
        await db.add_req(r.from_user.id, r.chat.id)


# ---------------- admins ----------------
@Client.on_message(filters.command("addadmin") & filters.private & owner_f)
async def addadmin(client, m):
    if len(m.command) < 2 or not m.command[1].isdigit():
        return await m.reply("Use: <code>/addadmin user_id</code>")
    uid = int(m.command[1])
    await db.admins.update_one({"_id": uid}, {"$set": {"_id": uid}}, upsert=True)
    await set_admin_menu(client, uid)
    await m.reply("✅ Admin added.")


@Client.on_message(filters.command("deladmin") & filters.private & owner_f)
async def deladmin(client, m):
    if len(m.command) < 2 or not m.command[1].isdigit():
        return await m.reply("Use: <code>/deladmin user_id</code>")
    await db.admins.delete_one({"_id": int(m.command[1])})
    await clear_admin_menu(client, int(m.command[1]))
    await m.reply("✅ Removed.")


@Client.on_message(filters.command("admins") & PM)
async def admins(client, m):
    ids = [str(a["_id"]) async for a in db.admins.find({})]
    await m.reply("👑 Owner: <code>%s</code>\nAdmins: %s" % (OWNER_ID, ", ".join(f"<code>{i}</code>" for i in ids) or "—"))


# ---------------- stats / broadcast / help ----------------
@Client.on_message(filters.command("stats") & PM)
async def stats(client, m):
    await m.reply(
        f"👥 Users: <b>{await db.users.count_documents({})}</b>\n"
        f"📢 Force-sub: <b>{await db.fsub.count_documents({})}</b>\n"
        f"✅ Verified: <b>{await db.verified.count_documents({})}</b>"
    )


@Client.on_message(filters.command("broadcast") & PM)
async def broadcast(client, m):
    if not m.reply_to_message:
        return await m.reply("Reply to a message with /broadcast.")
    ok = fail = 0
    status = await m.reply("📣 Broadcasting...")
    async for uid in db.all_users():
        try:
            await m.reply_to_message.copy(uid)
            ok += 1
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
        except Exception:
            fail += 1
        await asyncio.sleep(0.1)
    await status.edit_text(f"📣 Done. ✅ {ok} | ❌ {fail}")


@Client.on_message(filters.command("help") & PM)
async def help_cmd(client, m):
    await m.reply(
        "<b>Admin Commands Guide</b>\n"
        "/genlink – generate a link for a file or message\n"
        "/batch – batch link from the first and last channel posts\n"
        "/custom_batch – collect files one by one, then tap Stop\n"
        "/settings – welcome, verification, auto-delete, protection, texts\n"
        "/setdb – set the database channel\n"
        "/addfsub /delfsub /fsubs – force-sub channels (public/private/request)\n"
        "/addpremium /removepremium /premiums – manage premium users\n"
        "/addadmin /deladmin /admins – manage admins (owner)\n"
        "/testverify 1|2 – test a verification API\n"
        "/setlog – set the log channel (#NewUser, #BotRestarted)\n"
        "/revoke – revoke a permanent link\n"
        "/setmirror /swapdb – mirror (backup) channel\n"
        "/status – bot health, channels and statistics\n"
        "/connect /channels /chanlink – connected private channels + one-time join links\n"
        "/restart – restart the bot (owner)\n"
        "/stats /broadcast /cancel"
    )


@Client.on_message(filters.command("testverify") & PM)
async def testverify(client, m):
    stage = m.command[1] if len(m.command) > 1 else "1"
    if stage not in ("1", "2"):
        return await m.reply("Use: <code>/testverify 1</code> or <code>/testverify 2</code>")
    api_url, api_key = db.get(f"v{stage}_api_url"), db.get(f"v{stage}_api_key")
    if not api_url or not api_key:
        return await m.reply(
            f"❌ Verify-{stage} API URL/Key is not set.\nGo to /settings → 🔐 Verification and fill in both."
        )
    mode = int(db.get("verify_mode") or 0)
    short, info = await shorten(api_url, api_key, f"https://t.me/{client.me.username}?start=test")
    note = "" if mode >= int(stage) else f"\n\n⚠️ Verify Mode is currently <b>{mode}</b>. Enable it in settings (1 or 2 steps)."
    if short:
        alias = short.rstrip("/").split("/")[-1]
        warn = "" if len(alias) >= 15 else (
            "\n⚠️ This shortener did not use the custom alias, so its own shorter code is used."
        )
        await m.reply(
            f"✅ Verify-{stage} API is working correctly.\n<code>{html.escape(short)}</code>\n"
            f"🔤 Alias: <code>{html.escape(alias)}</code> ({len(alias)} chars){warn}{note}",
            disable_web_page_preview=True,
        )
    else:
        await m.reply(f"❌ Verify-{stage} fail:\n<code>{html.escape(info)}</code>{note}")


# ---------------- force-sub: add / remove from settings ----------------
def back_fsub():
    return Markup([[Btn("⬅️ Force-Sub", callback_data="pg_fsub")]])


async def save_fsub(chat, mode, link):
    await db.fsub.update_one(
        {"chat_id": chat["id"]},
        {"$set": {"chat_id": chat["id"], "mode": mode, "link": link, "title": chat["title"]}},
        upsert=True,
    )


@Client.on_callback_query(filters.regex(r"^(fs_add|fs_del_|fsm_)") & admin_f)
async def fsub_cb(client, q):
    d, uid = q.data, q.from_user.id
    if d == "fs_add":
        STATE[uid] = {"mode": "fsadd"}
        return await edit(
            q.message,
            "➕ <b>Add a Channel</b>\n\nSend the channel ID (<code>-100...</code>) or @username, "
            "or forward any message from that channel.\n⚠️ The bot must be an admin in that channel.\n\n/cancel = abort",
            Markup([[Btn("⬅️ Back", callback_data="pg_fsub")]]),
        )
    if d.startswith("fs_del_"):
        await db.fsub.delete_one({"chat_id": int(d[7:])})
        await q.answer("Removed")
        return await q.message.edit_reply_markup(await page_kb("fsub"))
    st = STATE.get(uid)
    if not st or st.get("mode") != "fsadd2":
        return await q.answer("Session expired. Tap Add Channel again.", show_alert=True)
    mode = d[4:]  # private | request
    try:
        link = (await client.create_chat_invite_link(
            st["chat_id"], creates_join_request=(mode == "request"))).invite_link
    except Exception as e:
        return await q.answer(f"Could not create the invite link: {e}"[:190], show_alert=True)
    STATE.pop(uid)
    await save_fsub({"id": st["chat_id"], "title": st["title"]}, mode, link)
    label = "Request" if mode == "request" else "Normal"
    await edit(q.message, f"✅ <b>{html.escape(st['title'])}</b> has been added ({label})", back_fsub())


async def fsadd_input(client, m):
    uid = m.from_user.id
    txt = (m.text or "").strip()
    if txt.startswith("/"):
        return
    info = fwd_info(m)
    if info:
        ref = info[0]
    elif txt.lstrip("-").isdigit():
        ref = int(txt)
    else:
        ref = txt.lstrip("@")
    if not ref:
        return await m.reply("❌ Send a channel ID, an @username, or a forwarded message from the channel.")
    try:
        chat = await client.get_chat(ref)
    except Exception as e:
        return await m.reply(f"❌ Channel not found: <code>{html.escape(str(e))}</code>")
    if not await is_bot_admin(client, chat.id):
        return await m.reply("❌ The bot is not an admin in that channel. Make it an admin and send it again.")
    if chat.username:  # public channel -> seedha add
        STATE.pop(uid, None)
        await save_fsub({"id": chat.id, "title": chat.title}, "public", f"https://t.me/{chat.username}")
        return await m.reply(f"✅ <b>{html.escape(chat.title)}</b> has been added (Public)", reply_markup=back_fsub())
    STATE[uid] = {"mode": "fsadd2", "chat_id": chat.id, "title": chat.title}
    await m.reply(
        f"🔒 <b>{html.escape(chat.title)}</b> is a private channel.\nChoose the join mode:",
        reply_markup=Markup([[Btn("✅ Normal", callback_data="fsm_private"),
                              Btn("📩 Request", callback_data="fsm_request")],
                             [Btn("⬅️ Back", callback_data="pg_fsub")]]),
    )


# ---------------- log channel + restart ----------------
@Client.on_message(filters.command("setlog") & PM)
async def setlog(client, m):
    if len(m.command) < 2:
        return await m.reply("Use: <code>/setlog -100xxxxxxxxxx</code> (to disable, use <code>/setlog off</code>)")
    if m.command[1].lower() == "off":
        await db.set("log_channel", 0)
        return await m.reply("✅ Log channel disabled.")
    if not m.command[1].lstrip("-").isdigit():
        return await m.reply("❌ Please send a valid channel ID.")
    cid = int(m.command[1])
    if not await is_bot_admin(client, cid):
        return await m.reply("❌ The bot is not an admin in that channel.")
    await db.set("log_channel", cid)
    await log_event(client, "✅ <b>Log channel connected.</b>\n#NewUser and #BotRestarted messages will appear here.")
    await m.reply(f"✅ Log channel set: <code>{cid}</code>")


@Client.on_message(filters.command("restart") & filters.private & owner_f)
async def restart(client, m):
    msg = await m.reply("🔄 <b>Restarting the bot...</b>")
    await db.cfg.update_one(
        {"_id": "restart"},
        {"$set": {"chat_id": m.chat.id, "msg_id": msg.id, "by": m.from_user.id}},
        upsert=True,
    )
    await asyncio.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)


# ---------------- permanent links ----------------
@Client.on_message(filters.command("revoke") & PM)
async def revoke(client, m):
    if len(m.command) < 2:
        return await m.reply("Use: <code>/revoke code_or_link</code>")
    code = m.command[1].rstrip("/").split("/")[-1]
    r = await db.links.update_one({"_id": code}, {"$set": {"revoked": True}})
    await m.reply("✅ Link revoked." if r.matched_count else "❌ Link not found.")


# ---------------- mirror channel ----------------
@Client.on_message(filters.command("setmirror") & PM)
async def setmirror(client, m):
    if len(m.command) < 2:
        return await m.reply("Use: <code>/setmirror -100xxxxxxxxxx</code> (to disable, use <code>/setmirror off</code>)")
    if m.command[1].lower() == "off":
        await db.set("mirror_channel", 0)
        return await m.reply("✅ Mirror channel disabled.")
    if not m.command[1].lstrip("-").isdigit():
        return await m.reply("❌ Please send a valid channel ID.")
    cid = int(m.command[1])
    if cid == int(db.get("db_channel") or 0):
        return await m.reply("❌ The mirror must be a different channel from the DB channel.")
    if not await is_bot_admin(client, cid):
        return await m.reply("❌ The bot is not an admin in that channel.")
    await db.set("mirror_channel", cid)
    await m.reply(
        f"✅ Mirror channel set: <code>{cid}</code>\n"
        "Files you save from now on with /genlink and /custom_batch are copied there too. "
        "Files saved earlier are not mirrored."
    )


@Client.on_message(filters.command("swapdb") & PM)
async def swapdb(client, m):
    mch = int(db.get("mirror_channel") or 0)
    if not mch:
        return await m.reply("❌ No mirror channel is set.")
    await db.set("db_channel", mch)
    await db.set("mirror_channel", 0)
    await m.reply(
        "✅ The mirror channel is now the main DB channel.\n"
        "Old links keep working through their mirror copies. Set a new mirror with /setmirror."
    )


# ---------------- /status ----------------
STARTED = time.time()


def _mem_mb():
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except Exception:
        pass
    return None


async def _chan_state(client, cid):
    if not cid:
        return "— not set"
    try:
        chat = await client.get_chat(int(cid))
    except Exception as e:
        return f"❌ cannot open ({html.escape(str(e))[:60]})"
    ok = await is_bot_admin(client, int(cid))
    title = html.escape(getattr(chat, "title", None) or str(cid))
    return f"✅ {title}" if ok else f"⚠️ {title} (the bot is not an admin)"


@Client.on_message(filters.command("status") & PM)
async def status(client, m):
    t0 = time.time()
    try:
        await db.cli.admin.command("ping")
        mongo = f"✅ OK ({int((time.time() - t0) * 1000)} ms)"
    except Exception as e:
        mongo = f"❌ {html.escape(str(e))[:80]}"
    try:
        st = await db.cli[DB_NAME].command("dbStats")
        size = f"{st.get('dataSize', 0) / 1048576:.1f} MB data / {st.get('storageSize', 0) / 1048576:.1f} MB stored"
    except Exception:
        size = "n/a"
    users = await db.users.count_documents({})
    prem = await db.premium.count_documents({"until": {"$gt": time.time()}})
    pend = await db.payments.count_documents({"status": "pending"})
    fsubs = await db.fsub.count_documents({})
    mem = _mem_mb()
    mode = int(db.get("verify_mode") or 0)
    flow = "Server" if int(db.get("verify_via_server") or 0) else "Direct"
    has = lambda n: "✅ set" if db.get(f"v{n}_api_url") and db.get(f"v{n}_api_key") else "— not set"  # noqa: E731
    free = int(db.get("free_limit") or 0)
    cd = int(db.get("link_cooldown") or 0)
    lines = [
        "📊 <b>Bot status</b>",
        "",
        f"⏱ Uptime: <b>{fmt_time(time.time() - STARTED)}</b>" + (f"   🧠 Memory: <b>{mem:.0f} MB</b>" if mem else ""),
        f"🗄 MongoDB: {mongo}",
        f"💾 Database size: <b>{size}</b>",
        "",
        f"👥 Users: <b>{users}</b>   💎 Premium: <b>{prem}</b>   💳 Pending payments: <b>{pend}</b>",
        f"📢 Force-sub channels: <b>{fsubs}</b>   📡 Connected channels: <b>{await db.channels.count_documents({})}</b>",
        "",
        f"📦 DB channel: {await _chan_state(client, db.get('db_channel'))}",
        f"🪞 Mirror channel: {await _chan_state(client, db.get('mirror_channel'))}",
        f"📝 Log channel: {await _chan_state(client, db.get('log_channel'))}",
        "",
        f"🔐 Verification: <b>{'Off' if not mode else f'{mode} step(s)'}</b> ({flow})   Shortener 1: {has(1)}   Shortener 2: {has(2)}",
        f"🎁 Free limit: <b>{free if free else 'Off'}</b>   ⏱ Cooldown: <b>{fmt_time(cd) if cd else 'Off'}</b>",
        f"🛠 Maintenance: <b>{'ON' if db.get('maintenance') else 'Off'}</b>   🌐 Website links: <b>{'ON' if db.get('permalink_enabled') else 'Off'}</b>",
    ]
    await m.reply("\n".join(lines))


# ---------------- connected channels + one-time join links ----------------
def back_joinch():
    return Markup([[Btn("⬅️ Channels", callback_data="pg_joinch")]])


@Client.on_message(filters.command("connect") & PM)
async def connect_cmd(client, m):
    STATE[m.from_user.id] = {"mode": "jcadd"}
    await m.reply(
        "📡 <b>Connect a channel</b>\n\nSend the channel ID (<code>-100...</code>) or @username, "
        "or forward any message from that channel.\n"
        "⚠️ The bot must be an admin there, with the right to invite users.\n\n/cancel = abort",
        reply_markup=back_joinch(),
    )


async def jcadd_input(client, m):
    uid = m.from_user.id
    txt = (m.text or "").strip()
    if txt.startswith("/"):
        return
    info = fwd_info(m)
    if info:
        ref = info[0]
    elif txt.lstrip("-").isdigit():
        ref = int(txt)
    else:
        ref = txt.lstrip("@")
    if not ref:
        return await m.reply("❌ Send a channel ID, an @username, or a forwarded message from the channel.")
    try:
        chat = await client.get_chat(ref)
    except Exception as e:
        return await m.reply(f"❌ Channel not found: <code>{html.escape(str(e))}</code>")
    if not await is_bot_admin(client, chat.id):
        return await m.reply("❌ The bot is not an admin in that channel. Make it an admin and send it again.")
    STATE.pop(uid, None)
    await db.channels.update_one(
        {"_id": chat.id}, {"$set": {"title": chat.title, "username": chat.username or "", "by": uid}}, upsert=True
    )
    await m.reply(
        f"✅ <b>{html.escape(chat.title)}</b> is connected.\nMake links with /chanlink.", reply_markup=back_joinch()
    )


@Client.on_callback_query(filters.regex(r"^(jc_add|jc_del_)") & admin_f)
async def jc_cb(client, q):
    if q.data == "jc_add":
        STATE[q.from_user.id] = {"mode": "jcadd"}
        return await edit(
            q.message,
            "📡 <b>Connect a channel</b>\n\nSend the channel ID (<code>-100...</code>) or @username, "
            "or forward any message from that channel.\n⚠️ The bot must be an admin there, with the right to "
            "invite users.\n\n/cancel = abort",
            back_joinch(),
        )
    await db.channels.delete_one({"_id": int(q.data[7:])})
    await q.answer("Disconnected")
    await q.message.edit_reply_markup(await page_kb("joinch"))


@Client.on_message(filters.command("channels") & PM)
async def channels_cmd(client, m):
    rows = [[Btn(f"🗑 {c['title']}", callback_data=f"jc_del_{c['_id']}")] async for c in db.channels.find({})]
    if not rows:
        return await m.reply("No connected channels yet. Use /connect.")
    await m.reply("📡 <b>Connected channels</b>\nTap 🗑 to disconnect one.", reply_markup=Markup(rows))


@Client.on_message(filters.command("chanlink") & PM)
async def chanlink_cmd(client, m):
    chans = [c async for c in db.channels.find({})]
    if not chans:
        return await m.reply("No connected channels yet. Connect one with /connect first.")
    STATE[m.from_user.id] = {"mode": "chanlink"}
    rows = [[Btn(f"📡 {c['title']}", callback_data=f"cl_{c['_id']}")] for c in chans[:20]]
    await m.reply(
        "🔗 <b>One-time join link</b>\n\n• To link to <b>one file</b>: forward that post from the connected channel "
        "here (or send its post link). I will check the post and show what it is.\n"
        "• To link to the <b>whole channel</b>: tap the channel below.\n\n/cancel = abort",
        reply_markup=Markup(rows),
    )


@Client.on_callback_query(filters.regex(r"^cl_-?\d+$") & admin_f)
async def chanlink_pick(client, q):
    chat = int(q.data[3:])
    ch = await db.channels.find_one({"_id": chat})
    if not ch:
        return await q.answer("This channel is no longer connected.", show_alert=True)
    STATE.pop(q.from_user.id, None)
    link = await build_link(client, f"j_{chat}_0")
    await q.answer()
    await edit(
        q.message,
        f"✅ <b>Channel link ready</b>\n📡 {html.escape(ch['title'])}\n\n<code>{link}</code>",
        Markup([[Btn("🔁 Share", url=f"https://t.me/share/url?url={link}")]]),
    )


@Client.on_message(PM, group=4)
async def chanlink_input(client, m):
    st = STATE.get(m.from_user.id)
    if not st or st.get("mode") != "chanlink" or (m.text and m.text.startswith("/")):
        return
    try:
        ref = await parse_ref(client, m)
    except Exception:
        ref = None
    if not ref:
        return await m.reply("❌ Forward a post from a connected channel, or send a t.me post link.")
    chat, mid = ref
    ch = await db.channels.find_one({"_id": chat})
    if not ch:
        return await m.reply("❌ That channel is not connected. Use /connect first.")
    try:
        msg = await client.get_messages(chat, mid)
    except Exception as e:
        return await m.reply(f"❌ Could not read that post: <code>{html.escape(str(e))[:120]}</code>")
    if not msg or msg.empty:
        return await m.reply("❌ That message does not exist (it may have been deleted).")
    STATE.pop(m.from_user.id, None)
    link = await build_link(client, f"j_{chat}_{mid}")
    await m.reply(
        f"✅ <b>One-time join link ready</b>\n📡 {html.escape(ch['title'])}\n"
        f"📄 Post #{mid}: {describe_post(msg)}\n\n<code>{link}</code>",
        reply_markup=Markup([[Btn("🔁 Share", url=f"https://t.me/share/url?url={link}")]]),
        disable_web_page_preview=True,
    )
