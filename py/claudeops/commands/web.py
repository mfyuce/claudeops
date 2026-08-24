"""`web` — yerel kontrol paneli: fleet durumunu göster, tek tek başlat/durdur.

Kullanıcı isteği: "hepsini açmam ama gerektiğinde web'den başlatırım, görürüm" +
seçenekli başlatma (model/permission-mode/effort/fresh) + tünelden (cf tunnel)
uzaktan erişim. Bu yüzden mass-start YOK — sadece roster'ı listele + her
satırda Start (seçeneklerle) / Stop.

Auth: token zorunlu (query param `?token=...`, sayfa + tüm /api/* istekleri).
Sebep: localhost-only için önemsizdi, ama tünelle internete açılabildiği için
(kullanıcı: "cf tunnel ile web'e ulaşırım") token ŞART — token yoksa herkes
fleet'i başlatıp durdurabilir. Token ~/.claude/claudeops/web.token'da persist
edilir (ilk çalıştırmada random üretilir, chmod 600).

Start = spawn_session(force_new=<UI seçimi>) — varsayılan resume (--new değil).
Stop = kill_session_and_parent(grace=KILL_GRACE_SECONDS) — aynı 10s
truncation-safe kural ([[claude-2183-conversation-truncation]]) + parent bash'i
de öldürür (orphan terminal bırakmaz, TODO-b kök sebep fix).
"""
from __future__ import annotations
import json
import os
import re
import secrets
import shutil
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from ..config import validate_config
from ..discovery import find_sessions, duplicates
from ..guard import guard_lock
from ..kill import kill_session_and_parent, KILL_GRACE_SECONDS
from ..paths import CLAUDEOPS_DIR, MODELS_TSV, ROSTER_TSV
from ..spawn import spawn_session, detect_display

DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"
TOKEN_FILE = os.path.join(CLAUDEOPS_DIR, "web.token")
TUNNEL_LOG = os.path.join(CLAUDEOPS_DIR, "tunnel.log")
_TUNNEL_URL_RE = re.compile(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com")

MODEL_CHOICES = [
    "claude-sonnet-5",
    "claude-opus-5",
    "claude-fable-5",
    "claude-haiku-4-5-20251001",
]
PERMISSION_MODES = ["auto", "acceptEdits", "bypassPermissions", "manual", "dontAsk", "plan"]
EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"]


def _load_or_create_token() -> str:
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            tok = f.read().strip()
            if tok:
                return tok
    except FileNotFoundError:
        pass
    tok = secrets.token_hex(24)
    os.makedirs(CLAUDEOPS_DIR, exist_ok=True)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(tok)
    return tok


def _start_tunnel(port: int, timeout: float = 20.0):
    """cloudflared quick tunnel başlat (login gerekmez, URL her seferinde random).

    Returns (proc, url_or_None). Süreç kalıcıdır — çağıran server_close/finally'de
    terminate etmeli, yoksa cloudflared orphan kalır.
    """
    os.makedirs(CLAUDEOPS_DIR, exist_ok=True)
    log_f = open(TUNNEL_LOG, "w")
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}"],
        stdout=log_f, stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + timeout
    url = None
    while time.monotonic() < deadline:
        try:
            with open(TUNNEL_LOG) as f:
                m = _TUNNEL_URL_RE.search(f.read())
                if m:
                    url = m.group(0)
                    break
        except FileNotFoundError:
            pass
        if proc.poll() is not None:
            break  # cloudflared erken çıktı — muhtemelen hata
        time.sleep(0.5)
    return proc, url


def _find_running(name: str) -> list:
    """Tam isim VEYA base eşleşmesiyle çalışan session'ları bul.

    rc.py'nin kill-first mantığıyla aynı desen ([[stale-tui-title-cross-suffix-resume]]
    tarzı): elle/eski tarih-suffix'li açılmış bir proc (`trino20260823`) roster'a
    temiz base isimle (`trino`) kaydedilse bile Session.base regex'i onu doğru
    eşler — çıplak `find_by_name` (tam isim) bunu KAÇIRIR → yanlışlıkla "duruyor"
    sanılıp ikinci bir proc spawn edilebilir.
    """
    return [s for s in find_sessions(measure_cpu=False) if s.name == name or s.base == name]


def _read_tsv_raw(path: str) -> list:
    """path'i YORUM DAHİL satır listesi olarak oku: [{"name","rest":[...],"active":bool}].

    models.tsv/roster.tsv'de kapalı/emekli girdiler `#isim\\t...` şeklinde yorumlanır
    (guard/roster.py bunları hiç görmez) — retire/reactivate için ham erişim gerekiyor.
    """
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return rows
    for line in lines:
        core = line.rstrip("\n")
        stripped = core.strip()
        if not stripped:
            continue
        active = not stripped.startswith("#")
        bare = stripped[1:] if not active else stripped
        parts = bare.strip().split("\t")
        if not parts or not parts[0]:
            continue
        rows.append({"name": parts[0], "rest": parts[1:], "active": active})
    return rows


def _fleet_status() -> dict:
    """İsim → {"cwd","model","state"} — state: active / closed (KAPALI) / retired (EMEKLİ).

    KAPALI  = roster.tsv'de aktif ama models.tsv'de yorumlu (guard açmaz, cwd hâlâ bilinir).
    EMEKLİ  = ikisinde de yorumlu (eski suffix-döneminden tam çıkarılmış isimler).
    """
    models_raw = {r["name"]: r for r in _read_tsv_raw(MODELS_TSV) if r["name"] != "name"}
    roster_raw = {r["name"]: r for r in _read_tsv_raw(ROSTER_TSV) if r["name"] != "name"}

    result = {}
    for name, mrow in models_raw.items():
        rrow = roster_raw.get(name)
        if rrow is None:
            continue  # cwd bilinmiyor — gösterilemez
        cwd = rrow["rest"][0] if rrow["rest"] else ""
        model = mrow["rest"][0] if mrow["rest"] else ""
        if mrow["active"] and rrow["active"]:
            state = "active"
        elif not mrow["active"] and not rrow["active"]:
            state = "retired"
        else:
            state = "closed"
        result[name] = {"cwd": cwd, "model": model, "state": state}
    return result


def _toggle_comment(path: str, name: str, want_active: bool) -> bool:
    """path'te `name` girdisinin satırını bul, want_active'e göre baştaki '#' ekle/kaldır.

    Satır bulunup değiştirildiyse True. Diğer satırlara/whitespace'e dokunmaz.
    """
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return False
    found = False
    for i, line in enumerate(lines):
        core = line.rstrip("\n")
        is_commented = core.startswith("#")
        bare = core[1:] if is_commented else core
        first_field = bare.strip().split("\t", 1)[0]
        if first_field == name:
            lines[i] = (bare if want_active else "#" + bare) + "\n"
            found = True
            break
    if found:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    return found


def _status_payload() -> dict:
    fleet = _fleet_status()
    running = {s.base: s for s in find_sessions(measure_cpu=True)}
    dups = duplicates(list(running.values()))
    ok, msg = validate_config()

    sessions, closed, retired = [], [], []
    for name in sorted(fleet):
        info = fleet[name]
        if info["state"] == "retired":
            retired.append({"name": name, "cwd": info["cwd"], "model": info["model"]})
            continue
        if info["state"] == "closed":
            closed.append({"name": name, "cwd": info["cwd"], "model": info["model"]})
            continue
        s = running.get(name)
        sessions.append({
            "name": name,
            "model": info["model"],
            "cwd": info["cwd"],
            "running": s is not None,
            "pid": s.pid if s else None,
            "cpu": round(s.cpu, 1) if s else None,
            "kind": ("fresh" if s.is_fresh else "resume") if s else None,
        })

    return {
        "config_ok": ok,
        "config_msg": msg,
        "dups": dups,
        "sessions": sessions,
        "closed": closed,
        "retired": retired,
        "model_choices": MODEL_CHOICES,
        "permission_modes": PERMISSION_MODES,
        "effort_levels": EFFORT_LEVELS,
    }


def _start(name: str, model: str = "", permission_mode: str = "", effort: str = "", fresh: bool = False) -> dict:
    fleet = _fleet_status()
    info = fleet.get(name)
    if not info or info["state"] != "active":
        return {"ok": False, "error": f"{name}: roster/models.tsv'de aktif değil"}
    if _find_running(name):
        return {"ok": False, "error": f"{name}: zaten çalışıyor"}
    try:
        with guard_lock(timeout=5.0):
            kind = spawn_session(
                name=name,
                cwd=info["cwd"],
                model=model.strip() or info["model"],
                display=detect_display(),
                permission_mode=permission_mode.strip() or "auto",
                effort=effort.strip() or "max",
                force_new=bool(fresh),
            )
    except TimeoutError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "kind": kind}


def _stop(name: str) -> dict:
    procs = _find_running(name)
    if not procs:
        return {"ok": False, "error": f"{name}: çalışmıyor"}
    try:
        with guard_lock(timeout=5.0):
            results = [kill_session_and_parent(s.pid, grace=KILL_GRACE_SECONDS) for s in procs]
    except TimeoutError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "result": results}


def _retire(name: str) -> dict:
    fleet = _fleet_status()
    info = fleet.get(name)
    if not info:
        return {"ok": False, "error": f"{name}: tanımsız"}
    if info["state"] == "retired":
        return {"ok": False, "error": f"{name}: zaten emekli"}
    procs = _find_running(name)
    if procs:
        try:
            with guard_lock(timeout=5.0):
                for s in procs:
                    kill_session_and_parent(s.pid, grace=KILL_GRACE_SECONDS)
        except TimeoutError as e:
            return {"ok": False, "error": str(e)}
    _toggle_comment(MODELS_TSV, name, want_active=False)
    _toggle_comment(ROSTER_TSV, name, want_active=False)
    return {"ok": True}


def _reactivate_and_start(name: str) -> dict:
    fleet = _fleet_status()
    info = fleet.get(name)
    if not info:
        return {"ok": False, "error": f"{name}: tanımsız"}
    if info["state"] == "active":
        return {"ok": False, "error": f"{name}: zaten aktif"}
    _toggle_comment(MODELS_TSV, name, want_active=True)
    _toggle_comment(ROSTER_TSV, name, want_active=True)
    return _start(name)


PAGE_HTML = """<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>claudeops</title>
<style>
  :root {
    --bg: #0d1117; --panel: #161b22; --panel2: #1c2129; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e;
    --green: #3fb950; --red: #f85149; --amber: #d29922;
    --accent: #58a6ff;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg: #f6f8fa; --panel: #ffffff; --panel2: #eef1f4; --border: #d0d7de;
      --text: #1f2328; --muted: #59636e;
      --green: #1a7f37; --red: #cf222e; --amber: #9a6700;
      --accent: #0969da;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 2rem 1.5rem 4rem;
    background: var(--bg); color: var(--text);
    font: 14px/1.5 ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  }
  .wrap { max-width: 960px; margin: 0 auto; }
  h1 { font-size: 1.1rem; margin: 0 0 .25rem; letter-spacing: .02em; }
  .sub { color: var(--muted); margin-bottom: 1.25rem; }
  .banner {
    padding: .5rem .75rem; border-radius: 6px; margin-bottom: .6rem;
    font-size: .85rem; border: 1px solid transparent;
  }
  .banner.bad { background: rgba(248,81,73,.12); border-color: var(--red); color: var(--red); }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; color: var(--muted); font-weight: 500; font-size: .75rem;
       text-transform: uppercase; letter-spacing: .04em; padding: .4rem .5rem;
       border-bottom: 1px solid var(--border); }
  td { padding: .4rem .5rem; border-bottom: 1px solid var(--border); vertical-align: middle; }
  td.cwd { color: var(--muted); font-size: .78rem; overflow: hidden; text-overflow: ellipsis;
           white-space: nowrap; max-width: 1px; }
  .tablewrap { overflow-x: auto; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: .4rem; }
  .dot.on { background: var(--green); }
  .dot.off { background: var(--muted); opacity: .5; }
  button, select, input[type=text] {
    font: inherit; padding: .3rem .6rem; border-radius: 6px; cursor: pointer;
    border: 1px solid var(--border); background: var(--panel); color: var(--text);
  }
  select, input[type=text] { cursor: default; }
  button.start { border-color: var(--green); color: var(--green); }
  button.stop { border-color: var(--red); color: var(--red); }
  button.go { border-color: var(--accent); color: var(--accent); }
  button.retire { border-color: var(--amber); color: var(--amber); font-size: .78rem; padding: .3rem .5rem; }
  button.reactivate { border-color: var(--green); color: var(--green); }
  button:disabled { opacity: .5; cursor: default; }
  .actioncell { display: flex; gap: .35rem; flex-wrap: wrap; }
  .group-title { color: var(--muted); font-size: .75rem; text-transform: uppercase;
                 letter-spacing: .04em; margin: 1.75rem 0 .4rem; }
  .opts-row td { background: var(--panel2); padding: .6rem .5rem; }
  .opts { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; }
  .opts label { color: var(--muted); font-size: .75rem; display: flex; flex-direction: column; gap: .15rem; }
  .fresh-toggle { flex-direction: row !important; align-items: center; gap: .35rem !important; }
</style>
</head>
<body>
<div class="wrap">
  <h1>claudeops — fleet control</h1>
  <div class="sub" id="summary">yükleniyor…</div>
  <div id="banners"></div>
  <div class="tablewrap">
  <table>
    <thead><tr>
      <th style="width:11%">isim</th>
      <th style="width:15%">model</th>
      <th style="width:9%">durum</th>
      <th style="width:6%">cpu%</th>
      <th style="width:8%">tür</th>
      <th>cwd</th>
      <th style="width:9%"></th>
    </tr></thead>
    <tbody id="rows"><tr><td colspan="7">yükleniyor…</td></tr></tbody>
  </table>
  </div>
  <div id="closedBox"></div>
  <div id="retiredBox"></div>
</div>
<script>
const TOKEN = new URLSearchParams(location.search).get('token') || '';
function withToken(url) {
  return url + (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(TOKEN);
}
let LAST = null;
let openOptionsFor = null;

async function refresh() {
  let r;
  try {
    r = await fetch(withToken('/api/status'));
  } catch (e) {
    document.getElementById('summary').textContent = 'sunucuya ulaşılamadı: ' + e;
    return;
  }
  if (r.status === 401) {
    document.getElementById('summary').textContent = '401 — token eksik/yanlış (URL\\'ye doğru ?token=... ekleyin)';
    return;
  }
  if (!r.ok || !(r.headers.get('content-type') || '').includes('application/json')) {
    document.getElementById('summary').textContent =
      'beklenmeyen yanıt (http ' + r.status + ') — bu tünel/URL artık geçerli olmayabilir, güncel linki kontrol edin';
    return;
  }
  const d = await r.json();
  LAST = d;
  render(d);
}

function render(d) {
  const running = d.sessions.filter(s => s.running).length;
  document.getElementById('summary').textContent =
    running + '/' + d.sessions.length + ' çalışıyor  ·  config: ' + d.config_msg;

  const banners = [];
  if (!d.config_ok) banners.push('<div class="banner bad">⚠ ' + d.config_msg + '</div>');
  if (d.dups.length) banners.push('<div class="banner bad">⚠ DUP: ' + d.dups.join(', ') + '</div>');
  document.getElementById('banners').innerHTML = banners.join('');

  const rows = [];
  for (const s of d.sessions) {
    const actionBtn = s.running
      ? `<button class="stop" onclick="act('${s.name}','stop',this)">durdur</button>`
      : `<button class="start" onclick="toggleOpts('${s.name}')">başlat ▾</button>`;
    rows.push(`
    <tr>
      <td>${s.name}</td>
      <td>${s.model || ''}</td>
      <td><span class="dot ${s.running ? 'on' : 'off'}"></span>${s.running ? 'pid ' + s.pid : 'durdu'}</td>
      <td>${s.running ? s.cpu.toFixed(1) : '—'}</td>
      <td>${s.kind || '—'}</td>
      <td class="cwd" title="${s.cwd}">${s.cwd}</td>
      <td><div class="actioncell">${actionBtn}
        <button class="retire" onclick="doRetire('${s.name}', this)">emekli et</button>
      </div></td>
    </tr>`);
    if (!s.running && openOptionsFor === s.name) {
      rows.push(optsRow(s, d));
    }
  }
  document.getElementById('rows').innerHTML = rows.join('');

  document.getElementById('closedBox').innerHTML = groupTable('Kapalı', d.closed, 'reactivate');
  document.getElementById('retiredBox').innerHTML = groupTable('Emekli', d.retired, 'reactivate');
}

function groupTable(title, items, action) {
  if (!items.length) return '';
  const rows = items.map(it => `
    <tr>
      <td style="width:14%">${it.name}</td>
      <td style="width:20%">${it.model || ''}</td>
      <td class="cwd" title="${it.cwd}">${it.cwd}</td>
      <td style="width:16%"><button class="reactivate" onclick="doReactivate('${it.name}', this)">tekrar işe al + başlat</button></td>
    </tr>`).join('');
  return `<div class="group-title">${title}</div>
    <div class="tablewrap"><table><tbody>${rows}</tbody></table></div>`;
}

function optsRow(s, d) {
  const modelOpts = ['(varsayılan: ' + s.model + ')', ...d.model_choices, 'diğer…']
    .map(m => `<option value="${m.startsWith('(') ? '' : m}">${m}</option>`).join('');
  const pmOpts = d.permission_modes.map(m => `<option ${m==='auto'?'selected':''}>${m}</option>`).join('');
  const efOpts = d.effort_levels.map(m => `<option ${m==='max'?'selected':''}>${m}</option>`).join('');
  return `
    <tr class="opts-row"><td colspan="7"><div class="opts">
      <label>model
        <select id="opt-model-${s.name}" onchange="this.nextElementSibling.style.display = this.value==='__other__' ? '' : 'none'">
          ${modelOpts.replace('value="diğer…"', 'value="__other__"')}
        </select>
      </label>
      <input type="text" id="opt-model-other-${s.name}" placeholder="model id" style="display:none">
      <label>permission-mode
        <select id="opt-pm-${s.name}">${pmOpts}</select>
      </label>
      <label>effort
        <select id="opt-effort-${s.name}">${efOpts}</select>
      </label>
      <label class="fresh-toggle"><input type="checkbox" id="opt-fresh-${s.name}"> yeni başlat (--new, geçmişi sıfırla)</label>
      <button class="go" onclick="doStart('${s.name}', this)">başlat</button>
      <button onclick="openOptionsFor=null; render(LAST)">vazgeç</button>
    </div></td></tr>`;
}

function toggleOpts(name) {
  openOptionsFor = (openOptionsFor === name) ? null : name;
  render(LAST);
}

async function doStart(name, btn) {
  const modelSel = document.getElementById('opt-model-' + name).value;
  const modelOther = document.getElementById('opt-model-other-' + name).value;
  const model = modelSel === '__other__' ? modelOther : modelSel;
  const permission_mode = document.getElementById('opt-pm-' + name).value;
  const effort = document.getElementById('opt-effort-' + name).value;
  const fresh = document.getElementById('opt-fresh-' + name).checked;
  btn.disabled = true;
  btn.textContent = 'başlıyor…';
  await call('start', {name, model, permission_mode, effort, fresh});
  openOptionsFor = null;
  refresh();
}

async function act(name, action, btn) {
  btn.disabled = true;
  btn.textContent = action === 'start' ? 'başlıyor…' : 'durduruluyor… (~10s)';
  await call(action, {name});
  refresh();
}

async function doRetire(name, btn) {
  if (!confirm(name + ': emekli edilsin mi? (çalışıyorsa önce durdurulur, models.tsv+roster.tsv\\'de yorumlanır — geri almak için "tekrar işe al" ile mümkün)')) return;
  btn.disabled = true;
  btn.textContent = 'emekli ediliyor…';
  await call('retire', {name});
  refresh();
}

async function doReactivate(name, btn) {
  btn.disabled = true;
  btn.textContent = 'başlıyor…';
  await call('reactivate', {name});
  refresh();
}

async function call(action, payload) {
  try {
    const r = await fetch(withToken('/api/' + action), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    if (r.status === 401) { alert('401 — token eksik/yanlış'); return; }
    const d = await r.json();
    if (!d.ok) alert(payload.name + ': ' + d.error);
  } catch (e) {
    alert('istek başarısız: ' + e);
  }
}

refresh();
setInterval(refresh, 4000);
</script>
</body>
</html>
"""

UNAUTHORIZED_HTML = b"<!doctype html><meta charset=utf-8><body style='font:14px monospace;padding:2rem'>401 &mdash; token eksik/yanlis. URL'ye <code>?token=...</code> ekleyin.</body>"


class _Handler(BaseHTTPRequestHandler):
    server_version = "claudeops-web/1"
    token = ""  # run() içinde atanır

    def log_message(self, fmt, *a):
        pass  # stdout'u kirletme — sessiz

    def _authorized(self) -> bool:
        qs = parse_qs(urlparse(self.path).query)
        given = (qs.get("token") or [""])[0]
        return secrets.compare_digest(given, self.token)

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _unauthorized(self):
        self.send_response(401)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(UNAUTHORIZED_HTML)))
        self.end_headers()
        self.wfile.write(UNAUTHORIZED_HTML)

    def do_GET(self):
        if not self._authorized():
            self._unauthorized()
            return
        path = urlparse(self.path).path
        if path == "/":
            body = PAGE_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/status":
            self._json(_status_payload())
        else:
            self._json({"error": "not found"}, status=404)

    def do_POST(self):
        if not self._authorized():
            self._unauthorized()
            return
        path = urlparse(self.path).path
        if path not in ("/api/start", "/api/stop", "/api/retire", "/api/reactivate"):
            self._json({"error": "not found"}, status=404)
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._json({"ok": False, "error": "geçersiz JSON"}, status=400)
            return
        name = str(data.get("name", "")).strip()
        if not name:
            self._json({"ok": False, "error": "name gerekli"}, status=400)
            return
        if path == "/api/start":
            result = _start(
                name,
                model=str(data.get("model", "")),
                permission_mode=str(data.get("permission_mode", "")),
                effort=str(data.get("effort", "")),
                fresh=bool(data.get("fresh", False)),
            )
        elif path == "/api/stop":
            result = _stop(name)
        elif path == "/api/retire":
            result = _retire(name)
        else:
            result = _reactivate_and_start(name)
        self._json(result)


def register(sub):
    p = sub.add_parser("web", help="yerel kontrol paneli (fleet'i tarayıcıdan/tünelden başlat-durdur)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--host", default=DEFAULT_HOST,
                   help=f"varsayılan {DEFAULT_HOST} (localhost). Tünel (cloudflared/ssh -L vb.) "
                        "için değiştirmeye gerek yok — tünel zaten localhost'a proxy eder.")
    p.add_argument("--print-token", action="store_true", help="sadece token'ı yazdır ve çık")
    p.add_argument("--tunnel", action="store_true",
                   help="cloudflared quick tunnel ile de dışarı aç (login gerekmez, URL her başlatmada değişir)")
    p.set_defaults(func=run)


def run(args) -> int:
    token = _load_or_create_token()
    if args.print_token:
        print(token)
        return 0

    tunnel_proc = None
    if args.tunnel:
        if shutil.which("cloudflared") is None:
            print("✗ cloudflared PATH'te yok — --tunnel için kurulu olmalı.")
            return 1
        print("cloudflared tünel başlatılıyor…")
        tunnel_proc, tunnel_url = _start_tunnel(args.port)
        if tunnel_url:
            print(f"  tünel  →  {tunnel_url}/?token={token}")
        else:
            print(f"  ⚠ tünel URL'i {TUNNEL_LOG} içinde bulunamadı (20s) — log'a bak, süreç yine de ayakta olabilir.")

    _Handler.token = token
    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    url = f"http://{args.host}:{args.port}/?token={token}"
    print(f"claudeops web  →  {url}")
    print(f"  token dosyası: {TOKEN_FILE} (chmod 600)")
    print("  Ctrl-C ile durdur.")
    if args.host not in ("127.0.0.1", "localhost"):
        print(f"  ⚠ {args.host}: localhost dışına bind — token olsa bile gereksiz risk, gerekmedikçe kullanma.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nkapatılıyor…")
    finally:
        server.server_close()
        if tunnel_proc is not None:
            tunnel_proc.terminate()
    return 0
