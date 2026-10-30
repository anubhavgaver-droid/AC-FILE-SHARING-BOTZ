import contextvars
import time

from motor.motor_asyncio import AsyncIOMotorClient

from config import BASE_URL, DB_CHANNEL, LOG_CHANNEL, DB_NAME, MONGO_URI, OWNER_ID

# Placeholders: {mention} {first} {time} {stage} {mode}
DEFAULTS = {
    "welcome_text": "👋 <b>Hello {mention}!</b>\n\nI am a file store bot. Open a shared link to receive your files.",
    "welcome_photo": "",  # photo URL or file_id
    "welcome_link": "",  # link whose preview card (image) is shown in /start, e.g. an ibb.co image page
    "welcome_preview_large": True,  # bigger preview card
    "welcome_preview_above": False,  # card above the text instead of below
    "welcome_buttons": "",  # har line: Label | https://link
    "wait_text": "⏳ <b>Please wait...</b>\nYour files are being delivered.",
    "fsub_text": "🚫 <b>Hey {mention}!</b>\n\nPlease join the channel(s) below first, then tap <b>Try Again</b>.",
    "verify_text": "🔐 <b>Verification {stage}/{mode}</b>\n\nTap <b>Verify Now</b> and complete the steps to get access for <b>{time}</b>.",
    "auto_delete_text": "⚠️ <b>These files will be deleted in {time}.</b>\nPlease save or forward them.",
    "protect_content": False,
    "auto_delete": 0,  # seconds, 0 = off
    "verify_mode": 0,  # 0 off, 1 = one step, 2 = two steps
    "v1_api_url": "",
    "v1_api_key": "",
    "v2_api_url": "",
    "v2_api_key": "",
    "verify_expire": 43200,  # seconds (access after the last step)
    "verify_gap": 3600,  # seconds: gap between the 1st and 2nd verification
    "verify_midnight_reset": False,  # a half-finished 2-step verification is reset at 12 midnight (IST)
    "verify_via_server": 0,  # 0 off | 1 server page -> shortener -> bot | 2 shortener -> server page -> bot
    "verify_min_time": 15,  # bypass protection (seconds)
    "shortener_alias": True,  # ask the shortener for a long random alias
    "alias_length": 15,  # characters after the short link domain (minimum 15, maximum 30)
    "verify_tutorial": "",
    "db_channel": DB_CHANNEL,
    "log_channel": LOG_CHANNEL,
    "permalink_enabled": False,  # website (permanent) links on/off
    "permalink_bot": "",  # redirect to this bot username; empty = this bot
    "link_expire": 0,  # seconds, 0 = never expires
    "site_name": "File Store",
    "site_tagline": "Fast, secure file sharing on Telegram.",
    "redirect_timer": 5,  # seconds shown on the website before redirecting (0 = instant)
    "plans_text": "💎 <b>Premium Plans</b>\n\n• 7 Days — ₹XX\n• 1 Month — ₹XX\n• 3 Months — ₹XX\n\nTap the button below to buy.",
    "sponsor_label": "🤝 Sponsor",
    "sponsor_url": "",
    "stream_enabled": True,
    "stream_expire": 21600,  # seconds, stream link kitni der valid
    "stream_base_url": BASE_URL,
    "premium_contact": "",  # @username or https:// link
    "premium_skip_verify": True,
    "premium_skip_fsub": False,
    "premium_no_autodelete": False,
    "free_limit": 0,  # links a new user may open before verification starts (0 = verify at once)
    "free_notice": True,  # tell the user how many free links are left
    "maintenance": False,
    "maintenance_text": "🛠 <b>The bot is under maintenance.</b>\nPlease try again a little later.",
    "mirror_channel": 0,  # backup copy of every saved file (see /setmirror)
    "plans_list": "7 Days | 7d | ₹49\n1 Month | 1m | ₹149\n3 Months | 3m | ₹399",  # Label | duration | price
    "pay_text": "💳 <b>Payment details</b>\n\nPay the exact amount, then send the payment screenshot here.",
    "pay_photo": "",  # QR code image (photo URL or file_id)
    "upi_id": "",  # shown in the payment message with a Copy button
    "premium_reminder": True,  # remind users before premium ends + tell them when it ended
    "premium_remind_before": 86400,  # seconds before the end (default 1 day)
    "join_enabled": True,  # one-time join links for connected channels
    "join_expire": 600,  # seconds an invite link stays valid
    "join_text": "✅ <b>Your file is ready!</b>\n\nTap <b>Join channel</b> to get in, then tap <b>Open the file</b>.\n⏳ This invite works for one person only and expires in {time}.",
    "features_text": (
        "✨ <b>Features</b>\n\n"
        "📁 Get files through secure links: single files, batches and whole collections\n"
        "⚡ Fast delivery straight into your chat\n"
        "🔐 Quick verification gives you access for a while\n"
        "💎 <b>Premium</b>: no verification, no waiting, online streaming with speed control "
        "(0.5x to 3x) and external player support (MX Player, VLC and more)\n"
        "⏱ Auto-delete and protected files when the admin turns them on\n"
        "📡 One-time join links for private channels\n"
        "💳 Buy premium inside the bot: send the payment screenshot and the admin approves it\n"
        "🌐 Permanent website links that keep working"
    ),
    "developer_name": "Bot Admin",
    "developer_link": "",  # @username or https:// link (adds a Developer button)
    "about_extra": "",  # optional extra line at the bottom of the About panel
    "button_style": "primary",  # colour of every inline button: primary (blue) | success (green) | danger (red) | off
    "smart_colors": True,  # Cancel buttons red, settings switches green when ON / blue when OFF
    "clone_enabled": False,  # users may request their own copy (clone) of this bot
    "clone_max_total": 3,  # clones running on this server at most
    "clone_max_per_user": 1,
    "quote_replies": False,  # False = replies are NOT sent as a quoted reply to the user's message
    "link_cooldown": 0,  # seconds a user must wait after opening a link before the next one (0 = off)
    "cooldown_text": "⏳ <b>Please wait {time}</b> before opening another link.",
    "premium_skip_cooldown": True,
}


# Clone bots get their own database; these settings can never be switched on there ...
CLONE_FORCED = {"permalink_enabled": False, "verify_via_server": 0, "stream_enabled": False, "clone_enabled": False}
# ... and these start empty, so a clone never inherits the main bot's channels / URLs.
CLONE_BLANK = {"db_channel": 0, "log_channel": 0, "stream_base_url": ""}


class Bot:
    """One running bot: the main bot (id 0) or a clone."""

    def __init__(self, bot_id, client, database, is_main=False, username=""):
        self.id, self.client, self.db, self.is_main, self.username = bot_id, client, database, is_main, username


BOTS = {}  # bot id -> Bot (running bots)
CURRENT = contextvars.ContextVar("current_bot", default=None)  # the bot that is handling the current update


class Database:
    def __init__(self, cli=None, name=None, owner_id=None, is_main=True):
        self.cli = cli or AsyncIOMotorClient(MONGO_URI)
        self.name = name or DB_NAME
        self.owner_id = OWNER_ID if owner_id is None else owner_id
        self.is_main = is_main
        d = self.cli[self.name]
        self.cfg = d.settings
        self.users = d.users
        self.admins = d.admins
        self.fsub = d.fsub
        self.reqs = d.join_requests
        self.tokens = d.verify_tokens
        self.verified = d.verified
        self.batches = d.custom_batches
        self.dq = d.delete_queue
        self.premium = d.premium
        self.links = d.links
        self.mirror = d.mirror
        self.channels = d.connected_channels
        self.joins = d.join_invites
        self.payments = d.payments
        self.clones = d.clones  # clone registry (used on the main database)
        self.clone_requests = d.clone_requests
        self.cache = dict(DEFAULTS)
        if not is_main:
            self.cache.update(CLONE_BLANK)

    async def load(self):
        doc = await self.cfg.find_one({"_id": "main"}) or {}
        for k, v in doc.items():
            if k != "_id":
                self.cache[k] = v
        await self.reqs.create_index([("uid", 1), ("chat_id", 1)])

    # ---- settings ----
    def get(self, key):
        if not self.is_main and key in CLONE_FORCED:
            return CLONE_FORCED[key]
        return self.cache.get(key, DEFAULTS.get(key))

    async def set(self, key, value):
        self.cache[key] = value
        await self.cfg.update_one({"_id": "main"}, {"$set": {key: value}}, upsert=True)

    # ---- users ----
    async def add_user(self, uid):
        """Returns True if the user is brand new (first time)."""
        r = await self.users.update_one({"_id": uid}, {"$setOnInsert": {"at": time.time()}}, upsert=True)
        return r.upserted_id is not None

    async def all_users(self):
        async for u in self.users.find({}, {"_id": 1}):
            yield u["_id"]

    # ---- admins ----
    async def is_admin(self, uid):
        return uid == self.owner_id or bool(await self.admins.find_one({"_id": uid}))

    # ---- join requests ----
    async def add_req(self, uid, chat_id):
        if not await self.has_req(uid, chat_id):
            await self.reqs.insert_one({"uid": uid, "chat_id": chat_id})

    async def has_req(self, uid, chat_id):
        return bool(await self.reqs.find_one({"uid": uid, "chat_id": chat_id}))

    # ---- premium ----
    async def premium_until(self, uid):
        d = await self.premium.find_one({"_id": uid})
        return d["until"] if d and d["until"] > time.time() else 0

    async def is_premium(self, uid):
        return bool(await self.premium_until(uid))

    async def add_premium(self, uid, seconds):
        until = max(await self.premium_until(uid), time.time()) + seconds
        await self.premium.update_one({"_id": uid}, {"$set": {"until": until}}, upsert=True)
        return until

    async def remove_premium(self, uid):
        return (await self.premium.delete_one({"_id": uid})).deleted_count

    # ---- free link limit ----
    async def free_used(self, uid):
        doc = await self.users.find_one({"_id": uid})
        return int((doc or {}).get("free_used", 0))

    async def bump_free(self, uid):
        await self.users.update_one({"_id": uid}, {"$inc": {"free_used": 1}}, upsert=True)

    async def reset_free(self, uid):
        await self.users.update_one({"_id": uid}, {"$set": {"free_used": 0}})

    # ---- link cooldown ----
    async def touch_open(self, uid):
        await self.users.update_one({"_id": uid}, {"$set": {"last_open": time.time()}}, upsert=True)

    async def last_open(self, uid):
        doc = await self.users.find_one({"_id": uid})
        return float((doc or {}).get("last_open", 0))

    # ---- mirror channel ----
    async def save_mirror(self, chat, mid, mchat, mmid):
        await self.mirror.update_one(
            {"_id": f"{chat}_{mid}"}, {"$set": {"mchat": mchat, "mid": mmid}}, upsert=True
        )

    async def get_mirrors(self, chat, ids):
        out = {}
        async for doc in self.mirror.find({"_id": {"$in": [f"{chat}_{i}" for i in ids]}}):
            out[doc["_id"]] = (doc["mchat"], doc["mid"])
        return out

    # ---- auto delete queue ----
    async def schedule_delete(self, chat_id, ids, delay):
        await self.dq.insert_one({"chat_id": chat_id, "ids": ids, "at": time.time() + delay})


MAIN_DB = Database()


class _DbProxy:
    """`db` always points at the database of the bot that is handling the current update
    (the main database when no clone is selected)."""

    def _cur(self):
        bot = CURRENT.get()
        return bot.db if bot is not None else MAIN_DB

    def __getattr__(self, name):
        return getattr(self._cur(), name)

    def __setattr__(self, name, value):
        setattr(self._cur(), name, value)


db = _DbProxy()
