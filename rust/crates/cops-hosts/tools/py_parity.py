"""Python tarafı parite kahini (`tests/parity.rs` çağırır): aynı girdileri Python `web_hosts`/`hosts`/`web_grpc`/
`web_steward` saf işlevlerine verip çıktıyı JSON olarak basar. Rust testi aynı girdileri crate'e verip karşılaştırır.

Koşum (yalnız testten): `python3 -I -B tools/py_parity.py <repo>/py < istek.json` (`-B`: `py/` altına bayt kodu yok)
- İstek: `{"op": [girdi, ...], ...}`; yanıt: `{"op": [çıktı, ...], ...}` (sıra korunur).
- YALITIM ZORUNLU: `CLAUDEOPS_DIR`, `HOME`, `CLAUDEOPS_DIAG_LOG` geçici dizinde olmalı, `CLAUDEOPS_EXTENSIONS=0`; aksi halde
  hiçbir modül içe aktarılmadan çıkılır (canlı `~/.claude/claudeops`a asla dokunulmaz).
- AĞSIZ: soket bağlantısı ve IP literali olmayan ad çözümü süreç içinde engellenir (deneme = istisna).
- Tek yazım: geçici `CLAUDEOPS_DIR` altındaki `hosts.json` (`save_host` girdileri).
"""
from __future__ import annotations

import json
import os
import pwd
import socket
import sys
import tempfile
import time


def _refuse(msg: str) -> None:
    sys.stderr.write(f"py_parity: {msg}\n")
    sys.exit(2)


def _isolated() -> str:
    real_home = os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir)
    tmp = os.path.realpath(tempfile.gettempdir())
    d = os.environ.get("CLAUDEOPS_DIR") or ""
    for key in ("CLAUDEOPS_DIR", "HOME", "CLAUDEOPS_DIAG_LOG"):
        v = os.path.realpath(os.environ.get(key) or "/")
        if not v.startswith(tmp + os.sep) or v.startswith(os.path.join(real_home, ".claude")):
            _refuse(f"{key} geçici dizinde değil")
    if os.environ.get("CLAUDEOPS_EXTENSIONS") != "0":
        _refuse("CLAUDEOPS_EXTENSIONS=0 değil")
    return real_home


def _no_network() -> None:
    def refuse(*_a, **_k):
        raise OSError("py_parity: ağ yasak")

    real_gai = socket.getaddrinfo

    def gai(host, port=None, family=0, type=0, proto=0, flags=0):
        # Yalnız sayısal çözüm (eski IPv4 biçimleri dahil, `inet_aton`): ad sunucusuna gidilmez.
        return real_gai(host, port, family, type, proto, flags | socket.AI_NUMERICHOST)

    socket.socket.connect = refuse          # type: ignore[assignment]
    socket.socket.connect_ex = refuse       # type: ignore[assignment]
    socket.create_connection = refuse       # type: ignore[assignment]
    socket.getaddrinfo = gai                # type: ignore[assignment]


def main() -> int:
    real_home = _isolated()
    _no_network()
    sys.path.insert(0, os.path.abspath(sys.argv[1]))
    # grpc/protobuf/websockets kullanıcı site dizininde (yalnız okuma; `-I` onu kendiliğinden eklemez).
    v = sys.version_info
    sys.path.insert(1, os.path.join(real_home, ".local", "lib", f"python{v.major}.{v.minor}", "site-packages"))

    from claudeops import authz, hosts, settings, term_dedup
    from claudeops.commands import web_grpc, web_hosts, web_steward
    from claudeops.proto import host_bridge_pb2 as pb2

    fake_settings: dict = {}
    settings.load_settings = lambda *a, **k: dict(fake_settings)      # type: ignore[assignment]
    web_hosts.load_settings = settings.load_settings                  # modül kendi adına bağlı

    req = json.load(sys.stdin)
    out: dict = {}

    def each(op, fn):
        if op in req:
            out[op] = [fn(x) for x in req[op]]

    # ── adres süzgeçleri ──
    def reach(x):
        if x["setting"] is None:
            fake_settings.pop("host_loopback_ports", None)
        else:
            fake_settings["host_loopback_ports"] = x["setting"]
        try:
            return {"ports": sorted(hosts.reach_loopback_ports()),
                    "urls": [hosts._is_reach_loopback(u) for u in x["urls"]]}
        finally:
            fake_settings.pop("host_loopback_ports", None)

    each("reach", reach)
    each("candidate_allowed", lambda x: web_hosts._candidate_allowed(x[0], x[1]))
    each("is_private_lan_http", web_hosts._is_private_lan_http)
    each("secret_safe_url", web_hosts._secret_safe_url)
    each("ip_is_blocked", hosts.ip_is_blocked)
    each("hostname_is_dns_name", hosts.hostname_is_dns_name)
    each("action_for", lambda x: authz.action_for(x[0], x[1]))
    each("urlencode", lambda pairs: __import__("urllib.parse").parse.urlencode([tuple(p) for p in pairs]))

    # ── kayıt doğrulama + upsert (geçici hosts.json) ──
    def save(x):
        path = hosts.HOSTS_JSON
        if x.get("existing") is None:
            if os.path.exists(path):
                os.remove(path)
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(x["existing"])
        r = hosts.save_host(*x["args"])
        return {"result": r, "hosts": hosts.load_hosts() if r.get("ok") else None}

    each("save_host", save)

    # ── indirgeme ──
    each("normalize_cli_options", web_hosts._normalize_cli_options)
    each("orphan_brief", web_hosts._orphan_brief)
    each("build_running", web_hosts._build_running)

    def fwd(x):
        try:
            return {"ok": web_hosts._fwd_brief(x["v"], x["now"])}
        except Exception as e:          # Python yakalamadığı istisnayla düşerse (parite farkı olarak görünür)
            return {"raised": type(e).__name__}

    each("fwd_brief", fwd)

    def finalize(x):
        real = time.time
        time.time = lambda: x["now"]        # type: ignore[assignment]
        try:
            return {"ok": web_hosts._finalize_remote_result(x["host"], x["raw"])}
        except Exception as e:
            return {"raised": type(e).__name__}
        finally:
            time.time = real                # type: ignore[assignment]

    each("finalize", finalize)

    def ws(kind):
        fn = web_hosts._parse_ws_status_frame if kind == "status" else web_hosts._parse_ws_term_frame

        def run(raw):
            web_hosts._bad_frame_log_last.clear()
            return fn(raw)
        return run

    each("ws_status", ws("status"))
    each("ws_term", ws("term"))
    each("valid_input_id", lambda v: term_dedup.valid_id(v) is not None)

    # ── önbellek, kademe, birleştirme ──
    def record(seq):
        web_hosts._cache.clear(), web_hosts._last_good.clear(), web_hosts._fail_streak.clear()
        res = []
        for r in seq:
            web_hosts._record_poll_result("h", r)
            c = web_hosts._cache.get("h")
            res.append({"cached": None if c is None else {"ok": c["ok"], "error": c.get("error"),
                                                           "sessions": c.get("sessions")},
                        "streak": web_hosts._fail_streak.get("h", 0)})
        return res

    each("record", record)

    def tiers(seq):
        web_hosts._tier.clear(), web_hosts._tier_downgrade_streak.clear()
        res = []
        for t in seq:
            web_hosts._update_tier("h", t)
            res.append(web_hosts.get_tier("h"))
        return res

    each("tiers", tiers)

    def merge(x):
        fake_settings["fleet_sort"] = x["fleet_sort"]
        web_hosts._cache.clear()
        real_time = time.time
        time.time = lambda: x["now"]        # type: ignore[assignment]
        try:
            for name, raw in x["raw"].items():
                web_hosts._cache[name] = web_hosts._finalize_remote_result(name, raw)
            for name, err in x.get("failed", {}).items():
                web_hosts._cache[name] = {"ok": False, "error": err, **web_hosts._EMPTY_REMOTE}
        finally:
            time.time = real_time           # type: ignore[assignment]
        real = hosts.load_hosts
        hosts.load_hosts = lambda: x["hosts"]       # type: ignore[assignment]
        try:
            mirrors = None if x["mirrors"] is None else set(x["mirrors"])
            return web_hosts.merge_status(x["payload"], mirrors)
        finally:
            hosts.load_hosts = real                 # type: ignore[assignment]
            fake_settings.pop("fleet_sort", None)

    each("merge", merge)

    # ── değnekçi istemci parçaları ──
    each("is_transport_error", lambda x: web_steward._is_transport_error(x[0], x[1], x[2]))
    each("host_fresh", lambda x: web_steward._host_fresh(x["st"], x["now"]))

    class _FakeRemote:
        def __init__(self, st):
            self.st = st

        def status(self, _host):
            return None if self.st is None else dict(self.st)

    def running_row(x):
        real = web_steward._remote
        st = x["st"]
        if st is not None and "last_ok_age" in st:        # `_remote_running_row` gerçek saatle tazelik denetler
            st = dict(st, last_ok_at=time.time() - st.pop("last_ok_age"))
        web_steward._remote = _FakeRemote(st)
        web_steward._HOST_HEALTH.clear()
        if x["backoff"]:
            web_steward._HOST_HEALTH["h"] = {"streak": 3, "until": time.time() + 600.0, "down": True}
        try:
            known, row = web_steward._remote_running_row("h", x["name"])
            return [known, row]
        finally:
            web_steward._remote = real
            web_steward._HOST_HEALTH.clear()

    each("running_row", running_row)

    def health(x):
        real = web_steward._remote
        web_steward._remote = _FakeRemote(x["st"])
        web_steward._HOST_HEALTH.clear()
        web_steward._CAPS.clear()
        web_hosts._last_try_at.clear()
        if x["backoff"]:
            web_steward._HOST_HEALTH["h"] = {"streak": 3, "until": x["now"] + 600.0, "down": True}
        if x["api"] is not None:
            web_steward._CAPS["h"] = (x["now"], {"api": x["api"], "capabilities": []})
        if x["last_try"]:
            web_hosts._last_try_at["h"] = x["last_try"]
        try:
            return web_steward.remote_health(["h"], x["now"])["h"]
        finally:
            web_steward._remote = real
            web_steward._HOST_HEALTH.clear()
            web_steward._CAPS.clear()
            web_hosts._last_try_at.clear()

    each("health", health)

    # ── gRPC: Python pb2 kodlar, iki taraf çözer ──
    def grpc_status(spec):
        m = pb2.StatusUpdate()
        for k in ("ok", "error", "extras_json"):
            if k in spec:
                setattr(m, k, spec[k])
        for k in ("cli_list", "dups"):
            getattr(m, k).extend(spec.get(k, []))
        for k in ("sessions", "closed", "retired"):
            for row in spec.get(k, []):
                getattr(m, k).add(**row)
        for cli, opts in spec.get("cli_options", {}).items():
            o = m.cli_options[cli]
            for f, vals in opts.items():
                getattr(o, f).extend(vals)
        return {"hex": m.SerializeToString().hex(), "dict": web_grpc._status_proto_to_dict(m)}

    def grpc_term(spec):
        m = pb2.TermUpdate(**spec)
        return {"hex": m.SerializeToString().hex(), "dict": web_grpc._term_proto_to_dict(m)}

    each("grpc_status", grpc_status)
    each("grpc_term", grpc_term)
    if "pb_fields" in req:
        out["pb_fields"] = {m.DESCRIPTOR.name: [[f.name, f.number] for f in m.DESCRIPTOR.fields]
                            for m in (pb2.PingRequest, pb2.PingResponse, pb2.StreamStatusRequest, pb2.CliOptions,
                                      pb2.SessionRow, pb2.StatusUpdate, pb2.StreamTermOutputRequest, pb2.TermUpdate)}

    # ── sabitler (içe aktarılmış değer; metin taraması değil) ──
    if "constants" in req:
        wh, ws_ = web_hosts, web_steward
        out["constants"] = {
            "STATUS_TIMEOUT_SECONDS": wh.STATUS_TIMEOUT_SECONDS,
            "TERM_READ_TIMEOUT_SECONDS": wh.TERM_READ_TIMEOUT_SECONDS,
            "ACTION_TIMEOUT_SECONDS": wh.ACTION_TIMEOUT_SECONDS,
            "POLL_INTERVAL_SECONDS": wh.POLL_INTERVAL_SECONDS,
            "FALLBACK_TIMEOUT_SECONDS": wh.FALLBACK_TIMEOUT_SECONDS,
            "TERM_ATTEMPT_TIMEOUT": wh.TERM_ATTEMPT_TIMEOUT,
            "TERM_MAX_ATTEMPTS": wh.TERM_MAX_ATTEMPTS,
            "CONSECUTIVE_FAILURES_BEFORE_ERROR": wh.CONSECUTIVE_FAILURES_BEFORE_ERROR,
            "STATUS_PUSH_SILENCE_SECONDS": wh.STATUS_PUSH_SILENCE_SECONDS,
            "POLLER_STALL_SECONDS": wh.POLLER_STALL_SECONDS,
            "WATCHDOG_INTERVAL_SECONDS": wh.WATCHDOG_INTERVAL_SECONDS,
            "_PROBE_MIN_GAP_SECONDS": wh._PROBE_MIN_GAP_SECONDS,
            "CAPABILITY_PROBE_INTERVAL_SECONDS": wh.CAPABILITY_PROBE_INTERVAL_SECONDS,
            "_GRPC_PROBE_TIMEOUT_SECONDS": wh._GRPC_PROBE_TIMEOUT_SECONDS,
            "_WS_PROBE_TIMEOUT_SECONDS": wh._WS_PROBE_TIMEOUT_SECONDS,
            "_CONSUMER_DEATH_LOG_MIN_INTERVAL_SECONDS": wh._CONSUMER_DEATH_LOG_MIN_INTERVAL_SECONDS,
            "_TERM_RELAY_IDLE_TTL_SECONDS": wh._TERM_RELAY_IDLE_TTL_SECONDS,
            "_TERM_RELAY_RESTART_MIN_INTERVAL_SECONDS": wh._TERM_RELAY_RESTART_MIN_INTERVAL_SECONDS,
            "_TERM_RELAY_SILENCE_SECONDS": wh._TERM_RELAY_SILENCE_SECONDS,
            "_INFLIGHT_MAX_SECONDS": wh._INFLIGHT_MAX_SECONDS,
            "_DEDUP_LAST_GOOD_MAX": wh._DEDUP_LAST_GOOD_MAX,
            "_CONN_POOL_MAX_IDLE": wh._CONN_POOL_MAX_IDLE,
            "_CLI_OPTIONS_FIELDS": list(wh._CLI_OPTIONS_FIELDS),
            "REFUSED_PREFIX": wh.REFUSED_PREFIX,
            "LOCAL_HOST_NAME": hosts.LOCAL_HOST_NAME,
            "LOOPBACK_REACH_DEFAULT": list(hosts.LOOPBACK_REACH_DEFAULT),
            "DNS_CHECK_TIMEOUT": hosts.DNS_CHECK_TIMEOUT,
            "ERR": hosts.ERR,
            "REMOTE_STALE_SECONDS": ws_.REMOTE_STALE_SECONDS,
            "REMOTE_BACKOFF_TICKS": ws_.REMOTE_BACKOFF_TICKS,
            "REMOTE_BACKOFF_SECONDS": ws_.REMOTE_BACKOFF_SECONDS,
            "MAX_DESTRUCTIVE_PER_HOST": ws_.MAX_DESTRUCTIVE_PER_HOST,
            "REMOTE_PROBES_PER_TICK": ws_.REMOTE_PROBES_PER_TICK,
            "REMOTE_CAPS_RECHECK_SECONDS": ws_.REMOTE_CAPS_RECHECK_SECONDS,
            "_EXTRA_KEYS": list(web_grpc._EXTRA_KEYS),
            "_OPTIONAL_SESSION_FIELDS": list(web_grpc._OPTIONAL_SESSION_FIELDS),
            "_OPTIONAL_TERM_FIELDS": list(web_grpc._OPTIONAL_TERM_FIELDS),
            "_KEEPALIVE_OPTIONS": [list(o) for o in web_grpc._KEEPALIVE_OPTIONS],
        }

    json.dump(out, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
