"""Web dashboard for the Smart Exit Manager.

A pure-stdlib HTTP server (no framework, zero dependencies) that exposes the
Dashboard layer in a browser: the Current Exit panel and the Node Table with
client-side search / filter / sort and one-click manual switch.

Design compliance: the browser only talks to this server, which reads state
through the Exit Manager and Node Pool (never a provider directly, Principle 5).
A background thread runs the supervise loop (health-check + policy reconcile);
all access to the Exit Manager is serialized with a lock so manual switches and
the background loop never race.

Endpoints:
    GET  /              -> the dashboard HTML page
    GET  /api/status    -> dashboard snapshot as JSON
    POST /api/switch    -> {"node_id": "..."} manual switch, returns snapshot
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .manager import SmartExitManager

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Smart VPNGate — Smart Exit Manager</title>
<style>
:root{--bg:#0e1116;--panel:#161b22;--line:#232a34;--fg:#e6edf3;--muted:#8b949e;
--accent:#3fb950;--warn:#d29922;--bad:#f85149;--chip:#21262d;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
header{padding:16px 20px;border-bottom:1px solid var(--line);display:flex;
align-items:center;gap:12px;flex-wrap:wrap}
h1{font-size:16px;margin:0;font-weight:600}
.tag{font-size:11px;color:var(--muted);border:1px solid var(--line);
border-radius:999px;padding:2px 8px}
main{padding:20px;max-width:1200px;margin:0 auto}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:16px 18px;margin-bottom:18px}
.exit-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
gap:12px}
.kv .k{color:var(--muted);font-size:12px}.kv .v{font-size:15px;font-weight:600;
word-break:break-all}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;
font-weight:600}
.healthy{background:rgba(63,185,80,.15);color:var(--accent)}
.degraded{background:rgba(210,153,34,.15);color:var(--warn)}
.down,.unknown{background:rgba(248,81,73,.12);color:var(--bad)}
.controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
input,select{background:var(--chip);border:1px solid var(--line);color:var(--fg);
border-radius:7px;padding:7px 10px;font-size:13px}
input{min-width:200px;flex:1}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);
white-space:nowrap}
th{color:var(--muted);cursor:pointer;user-select:none;font-weight:600}
th:hover{color:var(--fg)}
tr.current{background:rgba(63,185,80,.07)}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
button{background:var(--accent);color:#03130a;border:0;border-radius:6px;
padding:5px 12px;font-weight:600;cursor:pointer}
button:disabled{opacity:.4;cursor:default}
button.ghost{background:var(--chip);color:var(--fg);border:1px solid var(--line)}
.muted{color:var(--muted)}.right{margin-left:auto}
#err{color:var(--bad);margin-left:8px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.on{background:var(--accent)}.off{background:var(--bad)}
</style>
</head>
<body>
<header>
  <h1>🌐 Smart VPNGate</h1>
  <span class="tag">Smart Exit Manager</span>
  <span class="tag" id="provTag">provider: —</span>
  <label class="right muted"><input type="checkbox" id="auto" checked> auto-refresh</label>
  <span id="err"></span>
</header>
<main>
  <div class="card">
    <div class="k muted" style="margin-bottom:10px">
      <span class="dot" id="connDot"></span><span id="connText">…</span>
      <span id="policy" class="muted"></span>
    </div>
    <div class="exit-grid" id="exit"></div>
  </div>

  <div class="card">
    <div class="controls">
      <input id="q" placeholder="search country / ISP / node id…">
      <select id="fcountry"><option value="">all countries</option></select>
      <select id="fstatus">
        <option value="">all status</option>
        <option value="healthy">healthy</option>
        <option value="degraded">degraded</option>
        <option value="down">down</option>
        <option value="unknown">unknown</option>
      </select>
      <span class="muted right" id="count"></span>
    </div>
    <div style="overflow-x:auto">
      <table>
        <thead><tr id="head"></tr></thead>
        <tbody id="rows"></tbody>
      </table>
    </div>
  </div>
</main>
<script>
const COLS=[["current","•"],["country_short","Country"],["protocol","Proto"],
["status","Status"],["score","Score"],["latency_ms","Ping"],["loss","Loss"],
["download","DL"],["id","Node"],["_act","Action"]];
let sortKey="score",sortDir=-1,last=null;

function h(t){const d=document.createElement("div");d.textContent=t;return d.innerHTML;}
function badge(s){return `<span class="badge ${s||'unknown'}">${s||'unknown'}</span>`;}
function flag(cc){ // ISO alpha-2 -> emoji flag (regional indicators); degrades to code
  const c=(cc||"").toUpperCase();
  if(!/^[A-Z]{2}$/.test(c))return"";
  return String.fromCodePoint(0x1F1E6+c.charCodeAt(0)-65,0x1F1E6+c.charCodeAt(1)-65);
}
function country(cc){const f=flag(cc);return (f?f+" ":"")+h(cc||"—");}

function renderHead(){
  document.getElementById("head").innerHTML=COLS.map(([k,l])=>
    `<th data-k="${k}">${l}${k===sortKey?(sortDir<0?" ▼":" ▲"):""}</th>`).join("");
  document.querySelectorAll("th").forEach(th=>th.onclick=()=>{
    const k=th.dataset.k; if(k==="_act")return;
    if(k===sortKey)sortDir*=-1;else{sortKey=k;sortDir=(k==="id"||k==="country_short")?1:-1;}
    draw();
  });
}
function exitPanel(e){
  document.getElementById("provTag").textContent="provider: "+(e.provider||"—");
  const dot=document.getElementById("connDot"),txt=document.getElementById("connText");
  dot.className="dot "+(e.connected?"on":"off");
  txt.textContent=e.connected?"Connected":"Not connected"+(e.last_error?" — "+e.last_error:"");
  document.getElementById("policy").textContent=e.last_decision?
    `   ·   policy: ${e.last_decision.action} — ${e.last_decision.reason}`:"";
  const cells=[["Country",e.country_short?country(e.country_short):"—"],["Node",e.node_id||"—"],
    ["Protocol",e.protocol||"—"],["Health",badge(e.health)],
    ["Public IP",e.public_ip||"—"],["Uptime",e.connected_seconds?e.connected_seconds+"s":"—"]];
  document.getElementById("exit").innerHTML=cells.map(([k,v])=>
    `<div class="kv"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");
}
function draw(){
  if(!last)return;
  renderHead();
  const q=document.getElementById("q").value.toLowerCase();
  const fc=document.getElementById("fcountry").value;
  const fs=document.getElementById("fstatus").value;
  let rows=last.nodes.filter(n=>{
    if(fc&&n.country_short!==fc)return false;
    if(fs&&n.status!==fs)return false;
    if(q&&!(`${n.country_short} ${n.country} ${n.isp} ${n.id}`.toLowerCase().includes(q)))return false;
    return true;
  });
  rows.sort((a,b)=>{let x=a[sortKey],y=b[sortKey];
    if(typeof x==="string")return x.localeCompare(y)*sortDir;
    return ((x||0)-(y||0))*sortDir;});
  document.getElementById("count").textContent=`${rows.length} / ${last.total_nodes} nodes`;
  document.getElementById("rows").innerHTML=rows.map(n=>{
    const cur=n.current?"→":"";
    const dl=n.download?n.download.toFixed(1):"0";
    const loss=(n.loss*100).toFixed(0)+"%";
    const act=n.current?`<button disabled>active</button>`:
      `<button class="ghost" onclick="doSwitch('${n.id}')">switch</button>`;
    return `<tr class="${n.current?'current':''}">
      <td>${cur}</td><td>${country(n.country_short)}</td><td>${h(n.protocol)}</td>
      <td>${badge(n.status)}</td><td>${(n.score||0).toFixed(1)}</td>
      <td>${n.latency_ms||0}</td><td>${loss}</td><td>${dl}</td>
      <td class="mono">${h(n.id)}</td><td>${act}</td></tr>`;
  }).join("");
}
function fillCountries(){
  const sel=document.getElementById("fcountry"),cur=sel.value;
  sel.innerHTML='<option value="">all countries</option>'+
    last.countries.map(c=>`<option value="${c}">${flag(c)} ${c}</option>`).join("");
  sel.value=cur;
}
async function refresh(){
  try{
    const r=await fetch("/api/status");if(!r.ok)throw new Error("HTTP "+r.status);
    last=await r.json();document.getElementById("err").textContent="";
    exitPanel(last.current_exit);fillCountries();draw();
  }catch(e){document.getElementById("err").textContent="⚠ "+e.message;}
}
async function doSwitch(id){
  document.getElementById("err").textContent="switching to "+id+"…";
  try{
    const r=await fetch("/api/switch",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({node_id:id})});
    if(!r.ok)throw new Error("HTTP "+r.status);
    last=await r.json();document.getElementById("err").textContent="";
    exitPanel(last.current_exit);draw();
  }catch(e){document.getElementById("err").textContent="⚠ "+e.message;}
}
["q","fcountry","fstatus"].forEach(id=>document.getElementById(id).addEventListener("input",draw));
setInterval(()=>{if(document.getElementById("auto").checked)refresh();},5000);
refresh();
</script>
</body>
</html>
"""


class DashboardServer:
    """Runs the supervise loop in the background and serves the dashboard."""

    def __init__(self, app: SmartExitManager, host: str = "::", port: int = 8686,
                 tick_interval: float | None = None) -> None:
        self.app = app
        self.host = host
        self.port = port
        self.tick_interval = (
            tick_interval if tick_interval is not None else app.config.health.interval
        )
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._httpd: ThreadingHTTPServer | None = None
        self._tick_thread: threading.Thread | None = None

    # -- state access (all serialized) -------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            return self.app.dashboard()

    def switch(self, node_id: str) -> dict:
        with self._lock:
            self.app.exit.switch(node_id)
            return self.app.dashboard()

    def _tick_once(self) -> None:
        with self._lock:
            self.app.tick()

    # -- lifecycle ----------------------------------------------------------
    def _tick_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick_once()
            except Exception:  # noqa: BLE001 - never let the loop die
                pass
            self._stop.wait(self.tick_interval)

    def start(self, serve: bool = True) -> "DashboardServer":
        with self._lock:
            self.app.bootstrap()
        self._tick_thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._tick_thread.start()

        handler = _make_handler(self)
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self.port = self._httpd.server_address[1]  # resolve if port was 0
        if serve:
            try:
                self._httpd.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                self.stop()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        try:
            with self._lock:
                self.app.exit.disconnect()
        except Exception:  # noqa: BLE001
            pass


def _make_handler(server: DashboardServer):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence default stderr logging
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def do_GET(self):  # noqa: N802
            if self.path in ("/", "/index.html"):
                self._send(200, _PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif self.path == "/api/status":
                self._json(200, server.snapshot())
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if self.path != "/api/switch":
                self._json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                node_id = (json.loads(raw or b"{}") or {}).get("node_id", "")
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid JSON"})
                return
            if not node_id:
                self._json(400, {"error": "node_id required"})
                return
            self._json(200, server.switch(node_id))

    return Handler
