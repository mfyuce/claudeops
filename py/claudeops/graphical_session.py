"""Panelden grafik oturumu (X11/seat) öne alma: durum + `loginctl activate` (7 Kas 2026, sahip).

Çok-kullanıcılı makine: seat0'da iki hesap oturum açmış olabilir, ekranı yalnız biri (Active) görür. Uzak masaüstü
(uzakgoz) ancak kendi hesabımızın oturumu aktifken ekranı görür.

Güvenlik kuralları (sahip):
- Oturum YALNIZ `whoami` hesabından çözülür; argv'ye istemciden gelen HİÇBİR değer girmez (oturum no `loginctl`den okunur,
  yalnız rakam kabul edilir).
- Ekranı KİLİTLEME/KİLİDİ AÇMA (`lock`/`unlock`, 14 Kas sahip kararı) yalnız KENDİ oturumumuz için, açık onayla (`confirm=True`); açma
  `remote_desktop.unlock=off` ayarıyla tümden kapatılabilir. Parola alanına yazmak ayrı yol (uzakgoz girdisi).
- Başka bir kullanıcı aktifse onay (`confirm=True`) olmadan geçilmez, adı döner; `session_auto_activate` (varsayılan KAPALI)
  açıksa istemci (Uzak Masaüstü sekmesi) onaysız isteyebilir, çünkü ayar sahibin önceden verdiği onaydır.

Saf mantık + enjekte edilebilir `run` (testler gerçek `loginctl`e dokunmaz)."""
import getpass
import re
import subprocess
from typing import Any, Callable, Dict, List, Optional

from . import settings

GRAPHICAL_TYPES = ("x11", "wayland", "mir")
_DIGITS = re.compile(r"^[0-9]+$")
Runner = Callable[[List[str]], "subprocess.CompletedProcess"]


def _run(argv: List[str]) -> "subprocess.CompletedProcess":
    return subprocess.run(argv, capture_output=True, text=True, timeout=5)


def auto_activate_enabled() -> bool:
    """`session_auto_activate`: yalnız açık "on" sözcükleri açar (VARSAYILAN KAPALI; boş/tanınmayan = kapalı)."""
    v = settings.load_settings().get("session_auto_activate")
    return str(v if v is not None else "").strip().lower() in ("on", "1", "true", "yes")


def unlock_enabled() -> bool:
    """`remote_desktop.unlock` ayarı: yalnız açık kapatma sözcükleri ("off", "0", "false", "no") kapatır; yok/boş/tanınmayan = AÇIK."""
    raw = settings.load_settings().get("remote_desktop")
    v = raw.get("unlock") if isinstance(raw, dict) else None
    return str(v if v is not None else "").strip().lower() not in ("off", "0", "false", "no")


def _sessions(run: Runner) -> List[Dict[str, str]]:
    r = run(["loginctl", "--no-legend", "list-sessions"])
    rows: List[Dict[str, str]] = []
    if r.returncode != 0:
        return rows
    for line in r.stdout.splitlines():
        p = line.split()
        if len(p) >= 3 and _DIGITS.match(p[0]):
            rows.append({"id": p[0], "uid": p[1], "user": p[2], "seat": next((x for x in p[3:] if x.startswith("seat")), "")})
    return rows


def _props(run: Runner, sid: str) -> Dict[str, str]:
    r = run(["loginctl", "show-session", sid, "-p", "Active", "-p", "LockedHint", "-p", "Type", "-p", "State"])
    out: Dict[str, str] = {}
    for line in r.stdout.splitlines() if r.returncode == 0 else []:
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def status(run: Optional[Runner] = None, user: Optional[str] = None) -> Dict[str, Any]:
    """{ok, own: {id, active, locked, type}|None, active_user, other_active, auto}. Asla fırlatmaz.
    `active_user` = seat'te Active=yes olan oturumun sahibi ("" = bilinmiyor). Kilit True/False/None."""
    run = run or _run
    me = user or getpass.getuser()
    out: Dict[str, Any] = {"ok": False, "own": None, "active_user": "", "other_active": False, "auto": auto_activate_enabled(),
                           "unlock_enabled": unlock_enabled()}
    try:
        rows = _sessions(run)
        # Hesabın İLK oturumu değil, SEAT'li GRAFİK oturumu: ssh/tty oturumu (seat'siz ya da Type=tty/ssh) listede önce gelebilir
        # ve `loginctl activate` onu hedef alırsa yanlış oturum (ya da hiçbiri) öne alınır.
        mine = next((s for s in rows if s["user"] == me and s["seat"] and _props(run, s["id"]).get("Type") in GRAPHICAL_TYPES), None)
        for s in rows:
            props = _props(run, s["id"])
            active = props.get("Active") == "yes"
            if active and s["seat"]:        # ssh/seat'siz oturumun "Active"i ekranı görmek değildir
                out["active_user"] = s["user"]
            if s is mine:
                lk = props.get("LockedHint")
                out["own"] = {"id": s["id"], "active": active, "type": props.get("Type", ""),
                              "locked": True if lk == "yes" else False if lk == "no" else None}
        out["other_active"] = bool(out["active_user"]) and out["active_user"] != me
        out["ok"] = out["own"] is not None
        if not out["ok"]:
            out["error"] = "no_own_session"
    except Exception as e:  # noqa: BLE001 — durum uçları fırlatmaz
        out["error"] = f"{type(e).__name__}"
    return out


def activate(confirm: bool = False, run: Optional[Runner] = None, user: Optional[str] = None) -> Dict[str, Any]:
    """Kendi oturumumuzu öne al. Başka kullanıcı aktif ve `confirm` yoksa {ok:False, need_confirm:True, active_user}.
    Kilidi AÇMAZ. Sonuç: {ok, already?, need_confirm?, active_user?, error?}."""
    run = run or _run
    st = status(run, user)
    if not st["ok"]:
        return {"ok": False, "error": st.get("error", "no_own_session")}
    own = st["own"]
    if own["active"]:
        return {"ok": True, "already": True, "locked": own["locked"]}
    if st["other_active"] and not confirm:
        return {"ok": False, "need_confirm": True, "active_user": st["active_user"]}
    sid = own["id"]
    if not _DIGITS.match(sid):          # savunma: oturum no yalnız rakam
        return {"ok": False, "error": "bad_session_id"}
    r = run(["loginctl", "activate", sid])
    if r.returncode != 0:
        return {"ok": False, "error": ((r.stderr or r.stdout or "").strip()[-200:]) or "activate_failed"}
    after = status(run, user)
    return {"ok": bool(after["own"] and after["own"]["active"]), "locked": (after["own"] or {}).get("locked")}


def set_lock(action: str, confirm: bool = False, run: Optional[Runner] = None, user: Optional[str] = None,
             wait: float = 2.0, sleep: Callable[[float], None] = None) -> Dict[str, Any]:
    """Kendi grafik oturumumuzu kilitle (`lock`) ya da kilidini aç (`unlock`): `loginctl lock-session|unlock-session <id>`.
    Oturum YALNIZ `whoami` hesabının seat'li grafik oturumundan çözülür (`status`), argv'ye istemci değeri girmez, başka kullanıcı/oturum YOK.
    `confirm` yoksa {ok:False, need_confirm:True}. `unlock` ayar kapalıysa {ok:False, error:"unlock_disabled"}. Zaten istenen durumdaysa
    {ok:True, already:True}. Sonuç: {ok, action, locked, already?, error?}; `ok` kilit durumunun gerçekten değiştiğine bağlıdır (logind
    `LockedHint` kısa süre izlenir: kilit uygulaması asenkron)."""
    import time
    if action not in ("lock", "unlock"):
        return {"ok": False, "error": "bad_action"}
    if action == "unlock" and not unlock_enabled():
        return {"ok": False, "error": "unlock_disabled"}
    run = run or _run
    st = status(run, user)
    if not st["ok"]:
        return {"ok": False, "error": st.get("error", "no_own_session")}
    own = st["own"]
    want_locked = action == "lock"
    if own["locked"] is want_locked:
        return {"ok": True, "action": action, "already": True, "locked": own["locked"]}
    if not confirm:
        return {"ok": False, "need_confirm": True, "action": action}
    sid = own["id"]
    if not _DIGITS.match(sid):          # savunma: oturum no yalnız rakam
        return {"ok": False, "error": "bad_session_id"}
    r = run(["loginctl", f"{action}-session", sid])
    if r.returncode != 0:
        return {"ok": False, "action": action, "error": ((r.stderr or r.stdout or "").strip()[-200:]) or f"{action}_failed"}
    sleep = sleep or time.sleep
    deadline = time.monotonic() + wait
    locked = None
    while True:
        after = status(run, user)
        locked = (after["own"] or {}).get("locked")
        if locked is want_locked or time.monotonic() >= deadline:
            break
        sleep(0.25)
    return {"ok": locked is want_locked, "action": action, "locked": locked}
