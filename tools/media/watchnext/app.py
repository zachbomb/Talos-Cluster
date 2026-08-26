#!/usr/bin/env python3
"""Watch Next — a phone-friendly companion for the ambient Tunarr channels.

The ambient displays are silent, so they are a DISCOVERY surface: you catch
something on a muted screen and want it later, with sound. This app answers
"what is that?" and converts it into an intentional queue entry in one tap.

Deliberately stdlib-only so it runs from a ConfigMap on a stock python image
with no build step and no dependency surface.

"What's on now" is COMPUTED, not fetched: Tunarr's guide endpoint is slow and
schema-picky (500s on epoch ms, times out across 36 channels), but a channel is
a deterministic loop -- offset = (now - startTime) mod duration, then bisect
startTimeOffsets. No guide call, no flakiness, exact to the millisecond.

program.externalId is the Plex ratingKey, which is the join that makes saving work.
"""
import bisect, html, json, os, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TUNARR = os.environ.get("TUNARR_URL", "http://192.168.10.205:8000")
PLEX = os.environ.get("PLEX_URL", "http://192.168.10.203:32400")
PLEX_TOKEN = os.environ.get("PLEX_API", "")
SECTION = os.environ.get("PLEX_SECTION", "1")
QUEUE_TITLE = os.environ.get("QUEUE_TITLE", "Priority — Watch Next")
LIZ_ID = os.environ.get("PLEX_LIZ_ID", "109897463")
SW = {"X-Plex-Product": "WatchNext", "X-Plex-Version": "1.0",
      "X-Plex-Client-Identifier": "watchnext-001", "X-Plex-Platform": "Python",
      "X-Plex-Platform-Version": "3", "X-Plex-Device": "Server",
      "X-Plex-Device-Name": "watchnext"}
_tokens = {}
# channels to surface; empty = all non-stealth
ONLY = [c.strip() for c in os.environ.get("CHANNELS", "").split(",") if c.strip()]
CACHE_TTL = 30

_cache = {"t": 0, "v": None}


def jget(url, timeout=25):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def plex(path, method="GET", timeout=60, token=None):
    sep = "&" if "?" in path else "?"
    url = f"{PLEX}{path}{sep}X-Plex-Token={token or PLEX_TOKEN}"
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def user_token(user):
    """Resolve the PMS-usable token for a person.

    Saving to the wrong account is the failure this whole project already hit
    once: a Home-switch token authenticates to plex.tv but the SERVER 401s it,
    and while allowedNetworks covered the client the server ignored tokens
    entirely and silently wrote everything to the owner. The credential the PMS
    accepts is the per-server accessToken from /api/resources."""
    if user != "liz":
        return PLEX_TOKEN
    if "liz" in _tokens:
        return _tokens["liz"]
    req = urllib.request.Request(
        f"https://plex.tv/api/home/users/{LIZ_ID}/switch?X-Plex-Token={PLEX_TOKEN}",
        method="POST")
    for k, v in SW.items():
        req.add_header(k, v)
    acct = ET.fromstring(urllib.request.urlopen(req, timeout=30).read()
                         ).get("authenticationToken")
    mid = ET.fromstring(plex("/identity")).get("machineIdentifier")
    r2 = urllib.request.Request(
        f"https://plex.tv/api/resources?includeHttps=1&X-Plex-Token={acct}")
    for k, v in SW.items():
        r2.add_header(k, v)
    for d in ET.fromstring(urllib.request.urlopen(r2, timeout=30).read()).findall("Device"):
        if d.get("clientIdentifier") == mid and d.get("accessToken"):
            _tokens["liz"] = d.get("accessToken")
            return _tokens["liz"]
    raise RuntimeError("no server accessToken for liz")


def now_playing():
    """Compute the currently-airing program for each channel, plus how long is left."""
    if time.time() - _cache["t"] < CACHE_TTL and _cache["v"] is not None:
        return _cache["v"]
    out = []
    for ch in jget(f"{TUNARR}/api/channels"):
        if ch.get("stealth"):
            continue
        if ONLY and str(ch.get("number")) not in ONLY and ch.get("name") not in ONLY:
            continue
        start, dur = ch.get("startTime"), ch.get("duration")
        if not start or not dur:
            continue
        try:
            prog = jget(f"{TUNARR}/api/channels/{ch['id']}/programming", timeout=25)
        except Exception:
            continue
        offs, lineup = prog.get("startTimeOffsets") or [], prog.get("lineup") or []
        if not offs or not lineup:
            continue
        into = (int(time.time() * 1000) - start) % dur
        i = max(0, bisect.bisect_right(offs, into) - 1)
        entry = lineup[i]
        p = (prog.get("programs") or {}).get(entry.get("id"), {}).get("program") or {}
        ends_in = (offs[i] + (entry.get("duration") or 0) - into) // 1000
        out.append({
            "channel": ch.get("number"), "channelName": ch.get("name"),
            "title": p.get("title") or "(unknown)",
            "show": (p.get("show") or {}).get("title") if p.get("type") == "episode" else None,
            "year": (p.get("releaseDateString") or "")[:4],
            "summary": (p.get("summary") or "")[:400],
            "type": p.get("type"), "ratingKey": p.get("externalId"),
            "endsInSec": max(0, ends_in),
        })
    _cache.update(t=time.time(), v=out)
    return out


def queue_add(rating_key, token):
    """Append to the watch-next playlist, creating it on first use.

    Plex cannot create an EMPTY playlist -- creation requires at least one item -
    so the queue comes into existence on the first save rather than up front."""
    mid = ET.fromstring(plex("/identity", token=token)).get("machineIdentifier")
    base = f"server://{mid}/com.plexapp.plugins.library/library/metadata/"
    pls = ET.fromstring(plex("/playlists", token=token))
    for pl in pls.findall("Playlist"):
        if pl.get("title") == QUEUE_TITLE:
            q = urllib.parse.urlencode({"uri": base + str(rating_key)})
            plex(f"/playlists/{pl.get('ratingKey')}/items?{q}", "PUT", token=token)
            return "added"
    q = urllib.parse.urlencode({"type": "video", "title": QUEUE_TITLE,
                                "smart": "0", "uri": base + str(rating_key)})
    plex(f"/playlists?{q}", "POST", token=token)
    return "created"


PAGE = """<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Watch Next</title>
<style>
:root{--bg:#0e0f13;--card:#181a21;--fg:#e8e6e3;--dim:#9aa0ab;--accent:#d8734a;--line:#262a33}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{padding:18px 16px 10px;border-bottom:1px solid var(--line);display:flex;align-items:baseline;gap:12px}
h1{font-size:18px;margin:0;letter-spacing:.02em}
.who{margin-left:auto;display:flex;gap:6px}
.who button{background:var(--card);color:var(--dim);border:1px solid var(--line);border-radius:999px;padding:5px 12px;font-size:13px}
.who button[aria-pressed=true]{background:var(--accent);color:#12131a;border-color:var(--accent);font-weight:600}
main{padding:12px;display:grid;gap:12px;max-width:720px;margin:0 auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px}
.ch{font-size:12px;color:var(--dim);text-transform:uppercase;letter-spacing:.08em}
.t{font-size:19px;font-weight:650;margin:4px 0 2px;text-wrap:balance}
.meta{font-size:13px;color:var(--dim)}
.sum{font-size:13.5px;color:#bcc2cc;margin-top:8px;max-height:4.5em;overflow:hidden}
.row{display:flex;gap:8px;margin-top:12px;align-items:center}
button.save{background:var(--accent);color:#12131a;border:0;border-radius:10px;padding:9px 16px;font-weight:650;font-size:14px}
button.save:disabled{opacity:.5}
.ok{color:#7fca7f;font-size:13px}.err{color:#e2706a;font-size:13px}
.empty{color:var(--dim);text-align:center;padding:40px 12px}
</style>
<header><h1>Watch Next</h1>
<div class=who>
 <button data-u=zach aria-pressed=true>Zach</button>
 <button data-u=liz aria-pressed=false>Liz</button>
</div></header>
<main id=m><div class=empty>Loading…</div></main>
<script>
let who='zach';
document.querySelectorAll('.who button').forEach(b=>b.onclick=()=>{
  who=b.dataset.u;
  document.querySelectorAll('.who button').forEach(x=>x.setAttribute('aria-pressed',x===b));
});
function mmss(s){const m=Math.floor(s/60);return m>=60?`${Math.floor(m/60)}h ${m%60}m`:`${m}m`}
async function load(){
  const m=document.getElementById('m');
  try{
    const d=await (await fetch('/api/now')).json();
    if(!d.length){m.innerHTML='<div class=empty>No channels are airing right now.</div>';return}
    m.innerHTML=d.map(p=>`<div class=card>
      <div class=ch>Ch ${p.channel} · ${p.channelName}</div>
      <div class=t>${p.show?p.show+' — ':''}${p.title}</div>
      <div class=meta>${p.year||''}${p.year?' · ':''}${mmss(p.endsInSec)} left</div>
      ${p.summary?`<div class=sum>${p.summary}</div>`:''}
      <div class=row><button class=save data-k="${p.ratingKey||''}" ${p.ratingKey?'':'disabled'}>Save for later</button><span class=st></span></div>
    </div>`).join('');
    m.querySelectorAll('button.save').forEach(b=>b.onclick=async()=>{
      const st=b.parentElement.querySelector('.st');
      b.disabled=true;st.textContent='…';st.className='st';
      try{
        const r=await fetch('/api/save',{method:'POST',headers:{'content-type':'application/json'},
          body:JSON.stringify({ratingKey:b.dataset.k,user:who})});
        const j=await r.json();
        if(j.ok){st.textContent='Saved to '+who;st.className='st ok'}
        else{st.textContent=j.error||'failed';st.className='st err';b.disabled=false}
      }catch(e){st.textContent='failed';st.className='st err';b.disabled=false}
    });
  }catch(e){m.innerHTML='<div class=empty>Could not reach Tunarr.</div>'}
}
load();setInterval(load,30000);
</script>"""


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/api/now"):
            try:
                self._send(200, json.dumps(now_playing()))
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}))
        elif self.path in ("/healthz", "/health"):
            self._send(200, json.dumps({"ok": True}))
        else:
            self._send(200, PAGE, "text/html; charset=utf-8")

    def do_POST(self):
        if not self.path.startswith("/api/save"):
            return self._send(404, json.dumps({"error": "not found"}))
        try:
            n = int(self.headers.get("Content-Length") or 0)
            d = json.loads(self.rfile.read(n) or b"{}")
            rk = d.get("ratingKey")
            if not rk:
                return self._send(400, json.dumps({"ok": False, "error": "no ratingKey"}))
            res = queue_add(rk, user_token(d.get("user") or "zach"))
            self._send(200, json.dumps({"ok": True, "result": res}))
        except Exception as e:
            self._send(500, json.dumps({"ok": False, "error": str(e)}))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"watchnext listening on :{port}  tunarr={TUNARR} plex={PLEX}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
