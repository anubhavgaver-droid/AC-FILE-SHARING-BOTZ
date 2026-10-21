"""Permanent website links: https://your-domain/f/<code>  ->  current bot deep link."""
import html
import time

from aiohttp import web

from database import db

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
%%REFRESH%%<title>%%NAME%%</title>
<style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
font-family:system-ui,sans-serif;background:#0f1115;color:#eee;text-align:center}
.card{max-width:420px;padding:28px}
h1{font-size:20px;margin:0 0 8px}
p{opacity:.7;line-height:1.5}
a.btn{display:inline-block;margin-top:16px;background:#2a7fff;color:#fff;text-decoration:none;
padding:12px 22px;border-radius:12px;font-size:15px}
</style></head><body><div class="card"><h1>%%NAME%%</h1>
<p>%%TEXT%%</p>%%BUTTON%%</div></body></html>"""


def _page(name, text, url=None, status=200):
    refresh = f'<meta http-equiv="refresh" content="2;url={html.escape(url, quote=True)}">\n' if url else ""
    button = (
        f'<a class="btn" href="{html.escape(url, quote=True)}">Open in Telegram</a>' if url else ""
    )
    body = (
        PAGE.replace("%%REFRESH%%", refresh)
        .replace("%%NAME%%", html.escape(name))
        .replace("%%TEXT%%", text)
        .replace("%%BUTTON%%", button)
    )
    return web.Response(text=body, content_type="text/html", status=status)


async def go(request, client):
    name = db.get("site_name") or "File Store"
    doc = await db.links.find_one({"_id": request.match_info["code"]})
    if not doc:
        return _page(name, "This link does not exist.", status=404)
    if doc.get("revoked"):
        return _page(name, "This link has been revoked by the admin.", status=410)
    if doc.get("exp") and doc["exp"] < time.time():
        return _page(name, "This link has expired.", status=410)
    await db.links.update_one({"_id": doc["_id"]}, {"$inc": {"hits": 1}})
    username = (db.get("permalink_bot") or "").lstrip("@") or client.me.username
    url = f"https://t.me/{username}?start={doc['payload']}"
    return _page(name, "Opening Telegram…<br>If nothing happens, tap the button below.", url)


def setup(web_app, client):
    async def _go(request):
        return await go(request, client)

    web_app.add_routes([web.get("/f/{code}", _go)])
