import asyncio
import html
import logging
import math
import re
import time
from urllib.parse import quote

from aiohttp import web

from database import db
from helpers import base_url, is_streamable, media_of, parse_token

log = logging.getLogger("stream")
CHUNK = 1024 * 1024  # Pyrogram stream_media chunk = 1 MiB
_CACHE = {}

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%%TITLE%%</title>
<style>
body{margin:0;font-family:system-ui,sans-serif;background:#0f1115;color:#eee}
.wrap{max-width:900px;margin:0 auto;padding:16px}
h1{font-size:16px;word-break:break-word}
h2{font-size:13px;opacity:.7;margin:18px 0 6px;font-weight:600}
video,audio{width:100%;border-radius:12px;background:#000}
.row{display:flex;flex-wrap:wrap;gap:8px}
button,a.btn{background:#242833;color:#eee;border:0;border-radius:10px;padding:10px 14px;font-size:14px;
text-decoration:none;cursor:pointer}
button.on{background:#2a7fff;color:#fff}
small{opacity:.6;display:block;margin-top:14px;line-height:1.5}
</style></head><body><div class="wrap">
<h1>%%TITLE%%</h1>
<%%TAG%% id="p" src="%%SRC%%" controls preload="metadata" playsinline></%%TAG%%>
<h2>Playback speed</h2><div class="row" id="sp"></div>
<h2>Open in external player (Android)</h2>
<div class="row">
<a class="btn" href="%%MX%%">MX Player</a>
<a class="btn" href="%%MXPRO%%">MX Player Pro</a>
<a class="btn" href="%%PLAYIT%%">PLAYit</a>
<a class="btn" href="%%VLC%%">VLC</a>
<a class="btn" href="%%ANY%%">Other player…</a>
</div>
<h2>iPhone / other</h2>
<div class="row"><a class="btn" href="%%VLCIOS%%">VLC (iPhone)</a>
<button id="cp">Copy stream link</button></div>
<small>External player buttons work in Chrome on Android. In an external player, change the speed
from that player. This link is for you only, so please do not share it.</small>
<script>
const p=document.getElementById('p'),sp=document.getElementById('sp');
const speeds=[0.5,0.75,1,1.25,1.5,1.75,2,2.5,3];
function setSpeed(v){p.playbackRate=v;try{p.preservesPitch=true}catch(e){}
[...sp.children].forEach(b=>b.classList.toggle('on',+b.dataset.v===v));
try{localStorage.setItem('spd',v)}catch(e){}}
speeds.forEach(v=>{const b=document.createElement('button');b.textContent=v+'x';b.dataset.v=v;
b.onclick=()=>setSpeed(v);sp.appendChild(b)});
let s=1;try{s=parseFloat(localStorage.getItem('spd'))||1}catch(e){}
p.addEventListener('loadedmetadata',()=>setSpeed(s));setSpeed(s);
document.getElementById('cp').onclick=async()=>{try{await navigator.clipboard.writeText('%%SRC%%');
alert('Link copied')}catch(e){prompt('Copy link:','%%SRC%%')}};
</script></div></body></html>"""


async def _get_msg(client, chat, mid):
    key = (chat, mid)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[1] < 600:
        return hit[0]
    msg = await client.get_messages(chat, mid)
    _CACHE[key] = (msg, time.time())
    if len(_CACHE) > 300:
        _CACHE.pop(min(_CACHE, key=lambda k: _CACHE[k][1]), None)
    return msg


async def _load(request, client):
    tok = request.match_info["token"]
    data = parse_token(tok)
    if not data:
        raise web.HTTPForbidden(text="This link is invalid or has expired.")
    chat, mid, uid = data
    if not (await db.is_premium(uid) or await db.is_admin(uid)):
        raise web.HTTPForbidden(text="💎 Streaming is available for premium users only.")
    try:
        msg = await _get_msg(client, chat, mid)
    except Exception as e:
        log.warning("get_messages failed: %s", e)
        raise web.HTTPNotFound(text="File not found.")
    if not msg or msg.empty or not is_streamable(msg):
        raise web.HTTPNotFound(text="File not found.")
    return tok, msg


def _info(msg):
    media = media_of(msg)
    mime = getattr(media, "mime_type", None) or "application/octet-stream"
    name = getattr(media, "file_name", None) or f"file_{msg.id}"
    return media, mime, name


async def watch(request, client):
    tok, msg = await _load(request, client)
    media, mime, name = _info(msg)
    audio = bool(msg.audio or msg.voice) or mime.startswith("audio/")
    base = base_url() or f"https://{request.host}"
    src = f"{base}/stream/{tok}"
    rest = src.split("://", 1)[1]
    kind = "audio/*" if audio else "video/*"

    def intent(pkg=None):
        s = f"intent://{rest}#Intent;scheme=https;type={kind};"
        if pkg:
            s += f"package={pkg};"
        return s + f"S.title={quote(name)};end"

    page = (
        PAGE.replace("%%TITLE%%", html.escape(name))
        .replace("%%TAG%%", "audio" if audio else "video")
        .replace("%%SRC%%", src)
        .replace("%%MXPRO%%", intent("com.mxtech.videoplayer.pro"))
        .replace("%%MX%%", intent("com.mxtech.videoplayer.ad"))
        .replace("%%PLAYIT%%", intent("com.playit.videoplayer"))
        .replace("%%VLCIOS%%", "vlc-x-callback://x-callback-url/stream?url=" + quote(src, safe=""))
        .replace("%%VLC%%", intent("org.videolan.vlc"))
        .replace("%%ANY%%", intent())
    )
    return web.Response(text=page, content_type="text/html")


async def stream(request, client):
    tok, msg = await _load(request, client)
    media, mime, name = _info(msg)
    size = media.file_size
    start, end, status = 0, size - 1, 200

    rng = request.headers.get("Range")
    if rng:
        r = re.match(r"bytes=(\d*)-(\d*)", rng)
        if r and (r.group(1) or r.group(2)):
            s, e = r.groups()
            if not s:
                start = max(size - int(e), 0)
            else:
                start = int(s)
                if e:
                    end = min(int(e), size - 1)
            if start > end or start >= size:
                return web.Response(status=416, headers={"Content-Range": f"bytes */{size}"})
            status = 206
    length = end - start + 1
    headers = {
        "Content-Type": mime,
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(name)}",
        "Cache-Control": "no-store",
    }
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    if request.method == "HEAD":
        return web.Response(status=status, headers=headers)

    resp = web.StreamResponse(status=status, headers=headers)
    await resp.prepare(request)
    skip = start % CHUNK
    chunks = math.ceil((skip + length) / CHUNK)
    remaining = length
    try:
        async for chunk in client.stream_media(msg, limit=chunks, offset=start // CHUNK):
            if skip:
                chunk, skip = chunk[skip:], 0
            if len(chunk) > remaining:
                chunk = chunk[:remaining]
            await resp.write(chunk)
            remaining -= len(chunk)
            if remaining <= 0:
                break
    except (ConnectionResetError, asyncio.CancelledError):
        pass  # player ne connection band kar diya (seek/close)
    except Exception as e:
        log.warning("stream error: %s", e)
    return resp


def setup(web_app, client):
    async def _watch(r):
        return await watch(r, client)

    async def _stream(r):
        return await stream(r, client)

    web_app.add_routes([web.get("/watch/{token}", _watch), web.get("/stream/{token}", _stream)])
