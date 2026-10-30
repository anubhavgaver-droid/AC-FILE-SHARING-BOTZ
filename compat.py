"""Library compatibility layer (Pyrofork / Kurigram / Pyrogram forks).

1. Replies are NOT quoted by default: every Message.reply / reply_text gets quote=False
   (set 'Quote Replies' ON in /settings -> General to quote again).
3. Every inline button gets the colour chosen in /settings -> General -> Button Colour
   (default: blue, enums.ButtonStyle.PRIMARY) when the installed library supports button styles.
   With 'Smart Button Colours' ON: Cancel buttons are red, settings switches are green (✅) / blue (❌).
2. Old keyword `disable_web_page_preview=True` is translated to `link_preview_options` on forks that
   replaced it, and dropped on forks that have neither, so the same code runs on any of them.
"""
import copy
import functools
import inspect

from database import CURRENT, db


def _adapt(orig, quote_default=False):
    try:
        params = inspect.signature(orig).parameters
    except (TypeError, ValueError):
        params = {}
    var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    has_quote = "quote" in params
    has_dwp = "disable_web_page_preview" in params
    has_lpo = "link_preview_options" in params

    @functools.wraps(orig)
    async def wrapper(self, *args, **kw):
        if quote_default:
            explicit = "reply_parameters" in kw or "reply_to_message_id" in kw  # a reply target was given: keep it
            if has_quote or var_kw:
                if not explicit:
                    kw["quote"] = bool(db.get("quote_replies"))  # global switch, default: no quoting
            else:
                kw.pop("quote", None)  # this fork has no `quote` parameter
        if "disable_web_page_preview" in kw and not has_dwp and not var_kw:
            disabled = kw.pop("disable_web_page_preview")
            if disabled and has_lpo and "link_preview_options" not in kw:
                from pyrogram.types import LinkPreviewOptions

                kw["link_preview_options"] = LinkPreviewOptions(is_disabled=True)
        return await orig(self, *args, **kw)

    return wrapper


def _enum(name):
    try:
        from pyrogram.enums import ButtonStyle

        return getattr(ButtonStyle, name.upper())
    except Exception:
        return None


def _smart_style(text, callback_data):
    """Smart colours: Cancel buttons are red; a settings switch is green when ON (✅) and blue when OFF (❌).
    Returns a style name or None. (The small caps layer has already converted `text` when this runs.)"""
    cb = callback_data if isinstance(callback_data, str) else ""
    label = (text or "").lower() if isinstance(text, str) else ""
    if cb.endswith("cancel") or "cancel" in label or "ᴄᴀɴᴄᴇʟ" in label:
        return "danger"
    if cb.startswith("k_") and isinstance(text, str):
        tail = text.rstrip()
        if tail.endswith("✅"):
            return "success"
        if tail.endswith("❌"):
            return "primary"
    return None


def _style_value():
    name = (db.get("button_style") or "").strip().lower()
    if not name or name == "off":
        return None
    try:
        from pyrogram.enums import ButtonStyle

        return getattr(ButtonStyle, name.upper())
    except Exception:
        return None


def patch_buttons():
    """style=enums.ButtonStyle.PRIMARY on every InlineKeyboardButton (if this library version supports it)."""
    from pyrogram.types import InlineKeyboardButton

    orig = InlineKeyboardButton.__init__
    try:
        params = inspect.signature(orig).parameters
    except (TypeError, ValueError):
        return False
    if "style" not in params:
        return False  # older library: no coloured buttons, nothing to do

    @functools.wraps(orig)
    def init(self, *args, **kw):
        if "style" not in kw:
            style = _style_value()  # the base colour from /settings; 'off' switches every colour off
            if style is not None and db.get("smart_colors"):
                text = args[0] if args else kw.get("text")
                cb = kw["callback_data"] if "callback_data" in kw else (args[1] if len(args) > 1 else None)
                name = _smart_style(text, cb)
                style = (_enum(name) if name else None) or style
            if style is not None:
                kw["style"] = style
        orig(self, *args, **kw)

    InlineKeyboardButton.__init__ = init
    return True


def bind_handler(handler, bot):
    """A per-client copy of a handler that selects `bot` (its database, settings, owner) every time it runs.
    Needed because plugin handlers are shared objects but every clone must see its own data."""
    h = copy.copy(handler)
    cb = h.callback

    async def callback(*args, **kw):
        CURRENT.set(bot)
        return await cb(*args, **kw)

    functools.update_wrapper(callback, cb)
    h.callback = callback
    chk = getattr(h, "check", None)
    if chk is not None:

        async def check(*args, **kw):
            CURRENT.set(bot)
            return await chk(*args, **kw)

        h.check = check
    h._bot_bound = True
    return h


def patch_handlers():
    from pyrogram import Client

    orig = getattr(Client, "add_handler", None)
    if orig is None:
        return False

    @functools.wraps(orig)
    def add_handler(self, handler, group=0):
        bot = getattr(self, "bot_ctx", None)
        if bot is not None:
            handler = bind_handler(handler, bot)
        return orig(self, handler, group)

    Client.add_handler = add_handler
    return True


def patch():
    from pyrogram import Client
    from pyrogram.types import Message

    done = {}
    for cls, name, is_reply in (
        (Message, "reply_text", True),
        (Message, "reply", True),
        (Message, "edit_text", False),
        (Client, "send_message", False),
        (Client, "edit_message_text", False),
    ):
        orig = getattr(cls, name, None)
        if orig is None:
            continue
        if id(orig) not in done:  # `reply` is usually the same function as `reply_text`
            done[id(orig)] = _adapt(orig, quote_default=is_reply)
        setattr(cls, name, done[id(orig)])
    patch_buttons()
    patch_handlers()
