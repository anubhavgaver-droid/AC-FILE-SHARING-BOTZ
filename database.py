import time

from motor.motor_asyncio import AsyncIOMotorClient

from config import BASE_URL, DB_CHANNEL, LOG_CHANNEL, DB_NAME, MONGO_URI, OWNER_ID

# Placeholders: {mention} {first} {time} {stage} {mode}
DEFAULTS = {
    "welcome_text": "👋 <b>Hello {mention}!</b>\n\nI am a file store bot. Open a shared link to receive your files.",
    "welcome_photo": "",  # photo URL or file_id
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
}


class Database:
    def __init__(self):
        self.cli = AsyncIOMotorClient(MONGO_URI)
        d = self.cli[DB_NAME]
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
        self.cache = dict(DEFAULTS)

    async def load(self):
        doc = await self.cfg.find_one({"_id": "main"}) or {}
        for k, v in doc.items():
            if k != "_id":
                self.cache[k] = v
        await self.reqs.create_index([("uid", 1), ("chat_id", 1)])

    # ---- settings ----
    def get(self, key):
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
        return uid == OWNER_ID or bool(await self.admins.find_one({"_id": uid}))

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

    # ---- auto delete queue ----
    async def schedule_delete(self, chat_id, ids, delay):
        await self.dq.insert_one({"chat_id": chat_id, "ids": ids, "at": time.time() + delay})


db = Database()
