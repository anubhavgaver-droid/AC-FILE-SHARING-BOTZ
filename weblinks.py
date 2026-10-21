"""Website part of the bot: home page + permanent links  https://your-domain/f/<code>."""
import html
import json
import time

from aiohttp import web

from database import db

CSS = """
:root{--bg:#0b0d12;--card:#141821;--line:#262d3b;--text:#eef1f6;--muted:#9aa4b5;--accent:#2a7fff;--accent2:#5aa2ff}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;flex-direction:column;
font-family:Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--text);
background:radial-gradient(1100px 560px at 50% -10%,#16213a 0%,var(--bg) 62%)}
header{display:flex;align-items:center;gap:10px;padding:16px 20px;max-width:960px;width:100%;margin:0 auto}
.logo{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;font-size:18px;
background:linear-gradient(135deg,var(--accent),#7b5cff)}
header b{font-size:16px;letter-spacing:.2px}
main{flex:1;display:flex;align-items:center;justify-content:center;padding:14px}
.card{width:100%;max-width:440px;background:var(--card);border:1px solid var(--line);border-radius:22px;
padding:28px 24px;text-align:center;box-shadow:0 24px 70px rgba(0,0,0,.4)}
h1{font-size:22px;margin:0 0 6px}
p{color:var(--muted);line-height:1.55;margin:6px 0}
.small{font-size:12.5px;margin-top:16px}
.small a,footer a{color:var(--accent2);text-decoration:none}
.ring{position:relative;width:132px;height:132px;margin:20px auto 12px}
.ring svg{transform:rotate(-90deg)}
#ring{transition:stroke-dashoffset 1s linear}
.num{position:absolute;inset:0;display:grid;place-items:center;font-size:42px;font-weight:700}
.btn{display:block;width:100%;margin-top:12px;padding:14px 18px;border-radius:14px;font-size:15px;
font-weight:600;text-decoration:none;border:0;cursor:pointer;text-align:center;font-family:inherit}
.btn.primary{background:linear-gradient(135deg,var(--accent),#4d6bff);color:#fff}
.btn.ghost{background:transparent;color:var(--text);border:1px solid var(--line)}
.steps{list-style:none;padding:0;margin:22px 0 0;text-align:left;display:grid;gap:10px}
.steps li{display:flex;gap:12px;align-items:flex-start;color:var(--muted);font-size:14px;line-height:1.4}
.steps span{flex:none;width:24px;height:24px;border-radius:50%;background:#1d2433;color:var(--accent2);
display:grid;place-items:center;font-size:12px;font-weight:700}
.icon{font-size:44px;margin-bottom:6px}
footer{padding:18px;text-align:center;color:var(--muted);font-size:12.5px}
"""

LAYOUT = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0b0d12">
<title>%%TITLE%%</title>%%HEAD%%
<style>%%CSS%%</style></head><body>
<header><div class="logo">📁</div><b>%%NAME%%</b></header>
<main>%%MAIN%%</main>
<footer>Powered by <a href="%%BOTURL%%">@%%USER%%</a> · <a href="https://telegram.org/dl" rel="noopener">Get Telegram</a></footer>
%%SCRIPT%%</body></html>"""

STEPS = """<ul class="steps">
<li><span>1</span>Telegram opens with our bot.</li>
<li><span>2</span>Tap <b>START</b> if Telegram asks you to.</li>
<li><span>3</span>Your files are delivered to the chat.</li>
</ul>"""

REDIRECT_MAIN = """<div class="card">
<h1>Your files are almost ready</h1>
<p id="status">Redirecting…</p>
<div class="ring"><svg width="132" height="132" viewBox="0 0 132 132">
<defs><linearGradient id="g"><stop offset="0" stop-color="#5aa2ff"/><stop offset="1" stop-color="#7b5cff"/></linearGradient></defs>
<circle cx="66" cy="66" r="56" fill="none" stroke="#262d3b" stroke-width="8"/>
<circle id="ring" cx="66" cy="66" r="56" fill="none" stroke="url(#g)" stroke-width="8" stroke-linecap="round"
stroke-dasharray="351.86" stroke-dashoffset="0"/></svg><div class="num" id="num">%%TOTAL%%</div></div>
<a class="btn primary" href="%%URL%%">Open in Telegram now</a>
<button class="btn ghost" id="cancel" type="button">Cancel auto-redirect</button>
%%STEPS%%
<p class="small">Telegram app not opening? <a href="%%APP%%">Try the app link</a></p>
</div>"""

REDIRECT_JS = """<script>
(function(){
var URL_HTTP=%%URLJS%%,TOTAL=%%TOTAL%%,C=351.86,left=TOTAL,paused=false,timer=null;
var num=document.getElementById('num'),ring=document.getElementById('ring'),
st=document.getElementById('status'),cb=document.getElementById('cancel');
function render(){
  num.textContent=left;
  ring.style.strokeDashoffset=TOTAL>0?C*(1-left/TOTAL):C;
  st.textContent=left>0?'Redirecting in '+left+' second'+(left===1?'':'s')+'…':'Opening Telegram…';
}
function go(){window.location.href=URL_HTTP;}
function tick(){if(paused)return;left--;render();if(left<=0){clearInterval(timer);go();}}
cb.onclick=function(){
  paused=!paused;
  cb.textContent=paused?'Resume auto-redirect':'Cancel auto-redirect';
  if(paused){st.textContent='Auto-redirect cancelled. Tap the button above.';}else{render();}
};
if(TOTAL<=0){left=0;render();go();}else{render();timer=setInterval(tick,1000);}
})();
</script>"""

HOME_MAIN = """<div class="card">
<div class="icon">📁</div>
<h1>%%NAME%%</h1>
<p>%%TAGLINE%%</p>
<a class="btn primary" href="%%BOTURL%%">Open @%%USER%% in Telegram</a>
<a class="btn ghost" href="https://telegram.org/dl" rel="noopener">Get Telegram</a>
%%STEPS%%
</div>"""

ERROR_MAIN = """<div class="card">
<div class="icon">%%ICON%%</div>
<h1>%%HEADING%%</h1>
<p>%%TEXT%%</p>
<a class="btn primary" href="/">Go to homepage</a>
<a class="btn ghost" href="%%BOTURL%%">Open @%%USER%%</a>
</div>"""


def _username(client):
    return (db.get("permalink_bot") or "").lstrip("@") or client.me.username


def _render(client, title, main, head="", script=""):
    user = _username(client)
    name = html.escape(db.get("site_name") or "File Store")
    boturl = f"https://t.me/{user}"
    out = LAYOUT.replace("%%MAIN%%", main).replace("%%SCRIPT%%", script).replace("%%HEAD%%", head)
    for k, v in (("%%TITLE%%", html.escape(title)), ("%%NAME%%", name), ("%%CSS%%", CSS),
                 ("%%BOTURL%%", boturl), ("%%USER%%", html.escape(user)), ("%%STEPS%%", STEPS)):
        out = out.replace(k, v)
    return out


def _error(client, icon, heading, text, status):
    main = ERROR_MAIN.replace("%%ICON%%", icon).replace("%%HEADING%%", html.escape(heading)).replace(
        "%%TEXT%%", html.escape(text))
    page = _render(client, heading, main)
    return web.Response(text=page, content_type="text/html", status=status)


async def home(request, client):
    tagline = html.escape(db.get("site_tagline") or "Fast, secure file sharing on Telegram.")
    page = _render(client, db.get("site_name") or "File Store", HOME_MAIN.replace("%%TAGLINE%%", tagline))
    return web.Response(text=page, content_type="text/html")


async def go(request, client):
    doc = await db.links.find_one({"_id": request.match_info["code"]})
    if not doc:
        return _error(client, "🔎", "Link not found", "This link does not exist or was removed.", 404)
    if doc.get("revoked"):
        return _error(client, "🚫", "Link revoked", "This link has been revoked by the admin.", 410)
    if doc.get("exp") and doc["exp"] < time.time():
        return _error(client, "⌛", "Link expired", "This link has expired. Please ask for a new one.", 410)
    await db.links.update_one({"_id": doc["_id"]}, {"$inc": {"hits": 1}})

    user = _username(client)
    http_url = f"https://t.me/{user}?start={doc['payload']}"
    app_url = f"tg://resolve?domain={user}&start={doc['payload']}"
    v = db.get("redirect_timer")
    total = 5 if v is None else max(0, min(int(v), 60))

    esc = lambda s: html.escape(s, quote=True)  # noqa: E731
    main = (REDIRECT_MAIN.replace("%%TOTAL%%", str(total)).replace("%%URL%%", esc(http_url))
            .replace("%%APP%%", esc(app_url)))
    script = REDIRECT_JS.replace("%%URLJS%%", json.dumps(http_url).replace("</", "<\\/")).replace(
        "%%TOTAL%%", str(total))
    head = f'\n<noscript><meta http-equiv="refresh" content="{total + 1};url={esc(http_url)}"></noscript>'
    page = _render(client, "Opening Telegram…", main, head=head, script=script)
    return web.Response(text=page, content_type="text/html")


def setup(web_app, client):
    async def _go(request):
        return await go(request, client)

    async def _home(request):
        return await home(request, client)

    web_app.add_routes([web.get("/", _home), web.get("/f/{code}", _go)])
