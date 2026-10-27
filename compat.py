"""Library compatibility layer (Pyrofork / Kurigram / Pyrogram forks).

1. Replies are NOT quoted by default: every Message.reply / reply_text gets quote=False
   (set 'Quote Replies' ON in /settings -> General to quote again).
3. Every inline button gets the colour chosen in /settings -> General -> Button Colour
   (default: blue, enums.ButtonStyle.PRIMARY) when the installed library supports button styles.
2. Old keyword `disable_web_page_preview=True` is translated to `link_preview_options` on forks that
   replaced it, and dropped on forks that have neither, so the same code runs on any of them.
"""
import functools
import inspect

from database import db


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
            style = _style_value()
            if style is not None:
                kw["style"] = style
        orig(self, *args, **kw)

    InlineKeyboardButton.__init__ = init
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
