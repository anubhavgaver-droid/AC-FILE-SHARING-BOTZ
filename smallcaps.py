"""Converts every bot message / button label / menu description to small caps.

Tags, <code>/<pre> blocks, URLs, @usernames, /commands and #hashtags are left untouched.
"""
import re

from pyrogram import Client
from pyrogram.types import InlineKeyboardButton

_SRC = "abcdefghijklmnopqrstuvwxyz"
_DST = "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ"
assert len(_SRC) == len(_DST) == 26
_TABLE = {}
for _a, _b in zip(_SRC, _DST):
    _TABLE[ord(_a)] = _b
    _TABLE[ord(_a.upper())] = _b

_TOKEN = re.compile(
    r"(<[^>]*>|&[a-zA-Z]+;|&#\d+;|https?://[^\s<]+|\bt\.me/[^\s<]+|(?<!\w)[/@][A-Za-z0-9_]+|#[A-Za-z0-9_]+)"
)
_OPEN = re.compile(r"^<(code|pre)\b", re.I)
_CLOSE = re.compile(r"^</(code|pre)>", re.I)


def sc(text):
    if not text or not isinstance(text, str):
        return text
    out, depth = [], 0
    for i, part in enumerate(_TOKEN.split(text)):
        if i % 2:  # token -> as is
            if _OPEN.match(part):
                depth += 1
            elif _CLOSE.match(part):
                depth = max(0, depth - 1)
            out.append(part)
        else:
            out.append(part if depth else part.translate(_TABLE))
    return "".join(out)


def patch():
    o_send = Client.send_message
    o_edit = Client.edit_message_text
    o_cap = Client.edit_message_caption
    o_photo = Client.send_photo
    o_ans = Client.answer_callback_query
    o_btn = InlineKeyboardButton.__init__

    async def send_message(self, chat_id, text, *a, **kw):
        return await o_send(self, chat_id, sc(text), *a, **kw)

    async def edit_message_text(self, chat_id, message_id, text, *a, **kw):
        return await o_edit(self, chat_id, message_id, sc(text), *a, **kw)

    async def edit_message_caption(self, chat_id, message_id, caption, *a, **kw):
        return await o_cap(self, chat_id, message_id, sc(caption), *a, **kw)

    async def send_photo(self, chat_id, photo, caption="", *a, **kw):
        return await o_photo(self, chat_id, photo, sc(caption), *a, **kw)

    async def answer_callback_query(self, callback_query_id, text=None, *a, **kw):
        return await o_ans(self, callback_query_id, sc(text), *a, **kw)

    def btn_init(self, text, *a, **kw):
        o_btn(self, sc(text), *a, **kw)

    Client.send_message = send_message
    Client.edit_message_text = edit_message_text
    Client.edit_message_caption = edit_message_caption
    Client.send_photo = send_photo
    Client.answer_callback_query = answer_callback_query
    InlineKeyboardButton.__init__ = btn_init
