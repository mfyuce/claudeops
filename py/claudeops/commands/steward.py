"""`steward` (değnekçi) — projeleri gezen zamanlayıcının insan tarafı.

Kullanım:
  py/cops steward [-s|--steward SID] <alt-komut>   # kimlik: -s, yoksa COPS_STEWARD ortam değişkeni, yoksa default
  py/cops steward list                        # kimlikler: açık/kapalı, kip, proje sayısı, beyin
  py/cops steward create SID [--label "Ad"]   # yeni kimlik (ayar bloğu + dizin; varsayılan KAPALI + observe)
  py/cops steward remove SID                  # kimliği sil (projesi varsa REDDEDİLİR; dizin stewards/.removed/'e taşınır)
  py/cops steward transfer PROJE SID          # projeyi başka kimliğe devret (oturum kapalıyken; --force: denetimi atla)
  py/cops steward service add NAME --url URL --token-file PATH [--match prefix|exact] [--label L] / rm NAME / list
                                              # pasif paylaşımlı servis kaydı (varaka): makine geneli, oturumlarına HİÇ dokunulmaz
  py/cops steward [-s SID] jobs [list [--all|--state S]|show ID|poll|ack ID]   # dış iş kuyruğu (varaka) kayıtları / şimdi yokla
  py/cops steward status                      # özet: açık/kapalı, projeler faz faz, açık sorular, son tick
  py/cops steward projects [--phase planned]  # proje listesi
  py/cops steward cards [NAME] [--refresh]    # proje kartları (NAME: tek kartın tamamı); --refresh: şimdi yenile (panel üzerinden)
  py/cops steward set NAME [--phase planning] [--kind book] [--goal "..."] [--priority 2]
                           [--cadence 240] [--note "..."] [--model m] [--effort e]
                           [--host HOST [--force]]   # uzak proje (hosts.json adı; local = yerel): panel üzerinden
  py/cops steward import [--phase planned]    # roster'daki (değnekçide olmayan) projeleri toplu kaydet
  py/cops steward questions [--all]           # bana sorulanlar
  py/cops steward answer ID "cevap"           # cevapla (motor oturuma iletir)
  py/cops steward ideas [--all] / idea "metin"
  py/cops steward summary [--date YYYY-MM-DD] [--lang tr|en] [--save]   # günlük özet (log.jsonl'dan; panel gerekmez)
  py/cops steward log [-n 50]
  py/cops steward persona                     # etkin persona metni
  py/cops steward on|off / config KEY VALUE   # döngüyü aç-kapat / steward.<alan> ayarı (tick_seconds, max_active...)
  py/cops steward tick / tour / brain [status]|start|stop / directive NAME "metin" / restart NAME "direktif" --reason "..."
                                               (panel çalışıyor olmalı: /api/steward/* üzerinden)

Depo/ayar dosyaları: ~/.claude/claudeops/steward/ ve settings.json'daki `steward` alanı
(`py/cops config` ya da panel Ayarlar). Döngü yalnız `steward.enabled=on` iken kendiliğinden tick atar.
"""
from __future__ import annotations
import dataclasses
import json
import time
import types
import os
import shutil
import sys
from typing import Any, Dict, List

from .. import roster as roster_mod
from .. import steward as sw
from .. import steward_jobs as sj
from ..paths import CLAUDEOPS_DIR
from ..settings import load_settings, save_settings, steward_config, steward_ids
from . import mcp_queue

ENV_STEWARD = "COPS_STEWARD"

PHASE_ICON = {"idea": "💡", "planning": "📐", "planned": "🛠", "paused": "⏸", "done": "✅"}


def _sid(args) -> str:
    """Seçili kimlik (`resolve_sid` `run()`da doldurur); doğrudan çağrılan komutlarda yoksa default."""
    return getattr(args, "sid", None) or "default"


def resolve_sid(args) -> str:
    """`-s/--steward`, yoksa `COPS_STEWARD`, yoksa `default`. Geçersiz ya da ayarda tanımlı olmayan kimlik `ValueError`
    (sessizce default'a DÜŞMEZ: başka kimliğin deposuna yazılmasın)."""
    sid = (getattr(args, "steward", None) or os.environ.get(ENV_STEWARD) or "default").strip()
    if getattr(args, "action", None) in ("list", "create", "remove", "transfer", "service"):
        return sid      # kimlik yönetimi komutları seçili kimliği KULLANMAZ (kendi argümanları var)
    if sid != "default" and not sw.valid_steward_id(sid):
        raise ValueError(f"geçersiz değnekçi kimliği: {sid!r} (küçük harf, 2-16)")
    if sid not in steward_ids():
        raise ValueError(f"bilinmeyen değnekçi kimliği: {sid!r} (tanımlı: {', '.join(steward_ids())}); oluşturmak için: "
                         f"py/cops steward create {sid}")
    return sid


def _api(port: int, method: str, path: str, body: Dict[str, Any] | None = None, sid: str = "default") -> Dict[str, Any]:
    if sid != "default" and isinstance(body, dict):
        body = dict(body, steward=sid)      # default'ta gövde BUGÜNKÜYLE aynı (kimliksiz)
    try:
        return mcp_queue._api(port, method, path, body)
    except mcp_queue.ApiError as e:
        return {"ok": False, "error": str(e)}


def _sflag(sid: str) -> str:
    return "" if sid == "default" else f" -s {sid}"


def _ago(ts: float) -> str:
    if not ts:
        return "-"
    d = int(time.time() - ts)
    return f"{d // 86400}g" if d >= 86400 else f"{d // 3600}s" if d >= 3600 else f"{d // 60}dk"


_HEALTH_TR = {"ok": "taze", "down": "kapalı", "backoff": "geri çekilmede"}


def _remote_health_line(args, sid: str, hosts: List[str]) -> str:
    """`host=durum(api:N, yaş)` listesi; sağlık panelin önbelleğinde (bu süreçte yok): panel kapalı/eski ise zarifçe
    "bilinmiyor"."""
    res = _api(getattr(args, "port", mcp_queue.DEFAULT_PORT), "GET",
               "/api/steward/state" + ("" if sid == "default" else f"?steward={sid}"), None, sid)
    health = res.get("remote_hosts") if isinstance(res, dict) and res.get("ok") else None
    if not isinstance(health, dict):
        return "bilinmiyor (panel yanıt vermedi)  " + ", ".join(hosts)
    parts = []
    for h in hosts:
        e = health.get(h)
        if not isinstance(e, dict):
            parts.append(f"{h}=bilinmiyor")
            continue
        api = "?" if e.get("api") is None else str(e["api"])
        age = "" if e.get("age") is None else f", {_ago(time.time() - float(e['age']))} önce"
        parts.append(f"{h}={_HEALTH_TR.get(str(e.get('state')), 'bilinmiyor')} (api:{api}{age})")
    return "  ".join(parts)


def cmd_status(args) -> int:
    sid = _sid(args)
    cfg = steward_config(sid)
    projects = sw.load_projects(sid)
    qs = sw.open_questions(paths=sid)
    ideas = [i for i in sw.load_ideas(sid) if i.status == "new"]
    st = sw.load_state(sid)
    if sid != "default":
        print(f"kimlik: {sid}" + (f" ({cfg.label})" if cfg.label else ""))
    print(f"değnekçi: {'AÇIK' if cfg.enabled else 'KAPALI'}  mod={cfg.mode}  tick={cfg.tick_seconds}s  tur≥{cfg.tour_minutes}dk  "
          f"max_active={cfg.max_active}  beyin={cfg.brain_name} ({cfg.brain_cli} {cfg.brain_model or 'varsayılan'} {cfg.brain_effort})")
    counts = sw.summarize_projects(projects)
    print("projeler: " + "  ".join(f"{PHASE_ICON[p]} {p}={n}" for p, n in counts.items()) + f"  (toplam {len(projects)})")
    cards = sw.load_cards()
    print(f"kartlar: {len(cards)} (ham {sum(1 for c in cards.values() if not c.get('summarized', True))}, "
          f"bayat {sum(1 for c in cards.values() if c.get('stale'))})   kart yenileme: {'açık' if cfg.card_refresh else 'kapalı'}")
    print(f"açık soru: {len(qs)}   yeni fikir: {len(ideas)}   bekleyen madde: {st.get('pending_items', 0)}   "
          f"son tick: {_ago(float(st.get('last_tick') or 0))}   son tur: {_ago(float(st.get('last_tour') or 0))}")
    if st.get("ho_pending"):
        print("handover bekleyen: " + ", ".join(st["ho_pending"]))
    remote = sorted(f"{p.name}@{p.host}" for p in projects.values() if p.host)
    if remote:
        print(f"uzak projeler: {', '.join(remote)}   uzak eylem: {'açık' if cfg.remote_actions else 'kapalı'}")
        print("uzak host sağlığı: " + _remote_health_line(args, sid, sorted({p.host for p in projects.values() if p.host})))
    conflicts = sw.ownership_index(steward_ids()).get("conflicts") or {}
    mine = sorted(n for n in projects if n in conflicts)
    for n in mine:
        print(f"uyarı: sahiplik ÇAKIŞMASI '{n}' ({', '.join(conflicts[n])}): hiçbiri yönetmez; birinin projects.json'undan çıkarın")
    jobs = sj.load_jobs(sid)
    if jobs:
        open_n = sum(1 for j in jobs if sj.is_open(j))
        wait_n = sum(1 for j in jobs if sj.pending_stage(j))
        print(f"iş kuyruğu: {open_n} açık, {wait_n} iletilmemiş (py/cops steward{_sflag(sid)} jobs)")
    for q in qs[:5]:
        print(f"  ? [{q.id}] {q.project or '-'}: {q.text[:120]}")
    if not cfg.enabled:
        print(f"\naçmak için: py/cops steward{_sflag(sid)} on   (ya da panel Ayarlar) — hiçbir şey kendiliğinden başlamaz")
    return 0


def cmd_projects(args) -> int:
    projects = sw.load_projects(_sid(args))
    rows = sorted(projects.values(), key=lambda p: (p.priority, p.phase, p.name))
    if args.phase:
        rows = [p for p in rows if p.phase == args.phase]
    if not rows:
        print("değnekçi projesi yok — `py/cops steward import` roster'dakileri alır, `set NAME --phase ...` tek tek ekler")
        return 0
    cards = sw.load_cards()
    remote = any(p.host for p in rows)       # HOST sütunu yalnız uzak proje varken (yerel düzen eskisiyle aynı)
    hcol = f"{'HOST':<12}" if remote else ""
    print(f"{'NAME':<24}{'PHASE':<10}{hcol}{'P':>2} {'CAD':>5} {'VISIT':>6}  NEXT / GOAL")
    for p in rows:
        nxt = sw.card_one_liner(cards.get(p.name)) or p.goal
        h = f"{(p.host or 'local'):<12}" if remote else ""
        print(f"{p.name:<24}{p.phase:<10}{h}{p.priority:>2} {p.cadence_minutes:>5} {_ago(p.last_visit):>6}  {nxt[:70]}")
    return 0


def cmd_cards(args) -> int:
    """Kartları listele / tek kartı göster (dosyadan, panel gerekmez); `--refresh` panele yenileme işi bırakır."""
    if args.refresh:
        res = _api(args.port, "POST", "/api/steward/cards/refresh", {"name": args.name or ""}, _sid(args))
        print(json.dumps(res, ensure_ascii=False, indent=2))
        if res.get("ok"):
            print("arka planda yenileniyor; sonuç: py/cops steward cards   (ya da: py/cops steward log)")
        return 0 if res.get("ok") else 1
    if args.name:
        card = sw.load_card(args.name)
        if card is None:
            print(f"'{args.name}' için kart yok — py/cops steward cards --refresh {args.name}")
            return 1
        print("\n".join(sw.card_lines(card, True)))
        print(f"\n{json.dumps(card, ensure_ascii=False, indent=2)}")
        return 0
    cards = sw.load_cards()
    projects = sw.load_projects(_sid(args))
    if not cards:
        print("kart yok — `py/cops steward cards --refresh` (panel çalışıyorsa) ya da bir sonraki tick üretir")
    else:
        print(f"{'NAME':<24}{'AGE':>5}  {'':<6}NEXT STEP")
        for name, c in sorted(cards.items()):
            flag = "bayat" if c.get("stale") else ("ham" if not c.get("summarized", True) else "")
            print(f"{name:<24}{_ago(float(c.get('updated_at') or 0)):>5}  {flag:<6}{str(c.get('next_step') or '-')[:80]}")
    missing = sorted(n for n, p in projects.items() if p.phase in sw.ACTIVE_PHASES and n not in cards)
    if missing:
        print(f"\nkartı olmayan aktif proje: {len(missing)} ({', '.join(missing[:8])}{'…' if len(missing) > 8 else ''})")
    return 0


def cmd_set(args) -> int:
    fields = {"phase": args.phase, "kind": args.kind, "goal": args.goal, "priority": args.priority,
              "cadence_minutes": args.cadence, "notes": args.note, "model": args.model, "effort": args.effort}
    if getattr(args, "host", None) is not None:
        # Host (uzak proje) PANEL üzerinden yazılır: "projenin çalışan oturumu var mı" ve uzak roster denetimi panelin
        # uzak host önbelleğine bakar (bu süreçte yok).
        body = dict({k: v for k, v in fields.items() if v is not None}, name=args.name, host=args.host,
                    force=bool(getattr(args, "force", False)))
        res = _api(args.port, "POST", "/api/steward/project", body, _sid(args))
        if not res.get("ok"):
            print(f"hata: {res.get('error')}")
            return 1
        print(json.dumps(res.get("project") or {}, ensure_ascii=False, indent=2))
        if res.get("warning"):
            print(f"uyarı: {res['warning']}")
        return 0
    try:
        p = sw.upsert_project(args.name, paths=_sid(args), **{k: v for k, v in fields.items() if v is not None})
    except ValueError as e:
        print(f"hata: {e}")
        return 1
    sw.log_event("project_set", paths=_sid(args), name=p.name, fields=[k for k, v in fields.items() if v is not None], source="cli")
    print(json.dumps(dataclasses.asdict(p), ensure_ascii=False, indent=2))
    if p.host:
        print(f"not: '{p.name}' uzak proje ({p.host}): roster'ı o host'ta, panel denetler (yerel roster'a bakılmadı).")
    elif p.name not in {e.name for e in roster_mod.read_roster()}:
        print(f"uyarı: '{p.name}' roster'da yok — değnekçi oturum açamaz. Panelden kaydet ya da beyne "
              f"steward_register_project yaptır (klasör + GOAL.md + roster).")
    return 0


def cmd_drop(args) -> int:
    """Projeyi kimliğin kaydından çıkar (dinamik proje listesi; oturum/roster/klasör olduğu gibi kalır)."""
    sid = _sid(args)
    if not sw.remove_project(args.name, sid):
        print(f"hata: '{args.name}' bu kimliğin ({sid}) projesi değil")
        return 1
    sw.log_event("project_remove", paths=sid, name=args.name, source="cli")
    print(f"✓ '{args.name}' değnekçi kaydından çıkarıldı ({sid}); çalışan oturumu varsa artık yönetilmez")
    return 0


def cmd_import(args) -> int:
    sid = _sid(args)
    projects = sw.load_projects(sid)
    added = skipped = 0
    for e in roster_mod.read_roster():
        if e.name in projects or not sw.valid_name(e.name):
            continue
        try:
            sw.upsert_project(e.name, paths=sid, phase=args.phase, cadence_minutes=args.cadence)
        except ValueError:      # başka kimliğin projesi (OwnedElsewhere) ya da rezerve ad: atla
            skipped += 1
            continue
        added += 1
    print(f"{added} proje eklendi (faz={args.phase}, cadence={args.cadence} dk); amaç/tür için: py/cops steward{_sflag(sid)} set NAME --goal ..."
          + (f"  ({skipped} proje başka kimliğin ya da rezerve: atlandı)" if skipped else ""))
    return 0


def cmd_questions(args) -> int:
    qs = sw.load_questions(_sid(args)) if args.all else sw.open_questions(paths=_sid(args))
    if not qs:
        print("soru yok")
        return 0
    for q in qs:
        mark = "?" if q.status == "open" else ("✓" if q.delivered_at else "…")
        print(f"{mark} [{q.id}] {q.project or '-'} ({_ago(q.created_at)}): {q.text}")
        if q.options:
            print("    " + "  ".join(f"{i}) {o}" for i, o in enumerate(q.options, 1)))
        if q.answer:
            print(f"    → {q.answer}")
    return 0


def cmd_ask(args) -> int:
    """Panel üzerinden soru aç (bildirim + `/q/<id>` bağlantısı panelin işi): `py/cops steward ask [-p PROJE]
    [-o A -o B ...] "soru"`."""
    res = _api(args.port, "POST", "/api/steward/ask",
               {"project": args.project or "", "text": args.text, "options": args.option or [], "source": "cli"}, _sid(args))
    if not res.get("ok"):
        print(f"hata: {res.get('error')}")
        return 1
    print(f"✓ soru [{res['id']}] " + ("bildirildi" if res.get("notified") else "kaydedildi (ntfy yok ya da zaten bildirilmişti)")
          + (f"\n  {res['link']}" if res.get("link") else "  (tünel adresi yok: bağlantı üretilmedi)"))
    return 0


def cmd_answer(args) -> int:
    try:
        q = sw.answer_question(args.id, args.answer, _sid(args))
    except ValueError as e:
        print(f"hata: {e}")
        return 1
    if q is None:
        elsewhere = [s for s in sw.discover_steward_ids() if s != _sid(args) and sw.find_question(args.id, s) is not None]
        if elsewhere:      # soru devirle taşınmış olabilir: sessizce başka depoya yazmak yerine nerede olduğunu söyle
            print(f"soru bu kimlikte yok, başka kimlikte bulundu: {', '.join(elsewhere)}; "
                  f"cevap: py/cops steward{_sflag(elsewhere[0])} answer {args.id} \"...\"")
            return 1
        print("bilinmeyen soru id'si")
        return 1
    sw.log_event("answer", paths=_sid(args), id=q.id, project=q.project, source="cli")
    print(f"✓ cevaplandı — motor bir sonraki tick'te {q.project or 'beyne'} iletir (hemen: py/cops steward{_sflag(_sid(args))} tick)")
    return 0


def cmd_ideas(args) -> int:
    ideas = sw.load_ideas(_sid(args)) if args.all else [i for i in sw.load_ideas(_sid(args)) if i.status == "new"]
    if not ideas:
        print("fikir yok")
        return 0
    for i in ideas:
        print(f"[{i.id}] {i.status:<7} {i.project or '-':<16} {i.text[:140]}")
    return 0


def cmd_quota(args) -> int:
    """Kota bekçisi (TBD#116): status | check | mode off|manual|auto | limit N | final N | poll DAKİKA | day mon=80 tue=... (`day tue=` boşaltır)."""
    import time as _t
    from .. import steward_quota as sq
    act = args.quota_action
    cur = load_settings().get("steward_quota") or {}
    if act in ("mode", "limit", "shutdown", "final", "poll", "day"):
        patch: Dict[str, str] = {}
        if act == "mode":
            if args.value not in sq.MODES:
                print(f"mod: {'|'.join(sq.MODES)}", file=sys.stderr)
                return 1
            patch["mode"] = args.value
        elif act in ("limit", "shutdown", "final", "poll"):
            try:
                float(args.value)
            except ValueError:
                print("sayı ver (kullanılan %, poll için dakika)", file=sys.stderr)
                return 1
            patch[{"limit": "manual_limit", "shutdown": "shutdown_limit", "final": "final_limit", "poll": "poll_minutes"}[act]] = args.value
        else:
            for a in [args.value] + list(args.more or []):
                k, _, v = (a or "").partition("=")
                if k not in sq.DAYS:
                    print(f"gün: {','.join(sq.DAYS)} (örn tue=80); gün sıfırlanmadan itibaren sayılır: Pzt 18:00 sonrası = SALI", file=sys.stderr)
                    return 1
                patch["day_" + k] = v.strip()
        save_settings({"steward_quota": patch})
        print("✓ kaydedildi (servis bir sonraki tick'te okur)")
        cur = load_settings().get("steward_quota") or {}
    if act == "check":
        from . import web_steward
        u = web_steward.quota_read_usage()
        if u is None:
            print("kullanım okunamadı (claude -p /usage)")
            return 1
        d = sq.decide(cur, u, _t.time())
        print(f"kullanılan %{u.week_pct:g} (Fable %{u.fable_pct}) sıfırlanma {_t.strftime('%d.%m %H:%M', _t.localtime(u.reset_ts)) if u.reset_ts else '?'}")
        print(f"bugün: {sq.day_label(u, _t.time())}  tavan: {d.cap}  karar: {d.action} {d.reason}")
        return 0
    print("kota bekçisi: " + (json.dumps(cur, ensure_ascii=False) if cur else "ayar yok (mode=off)"))
    try:
        with open(os.path.join(CLAUDEOPS_DIR, "steward", "quota.json"), encoding="utf-8") as f:
            st = json.load(f)
        d = st.get("decision") or {}
        print(f"son okuma: {_t.strftime('%d.%m %H:%M', _t.localtime(st.get('at') or 0))}  kullanılan: %{(st.get('usage') or {}).get('week_pct')}  "
              f"karar: {d.get('action')} (tavan {d.get('cap')}) {d.get('reason', '')}  durduruldu: {st.get('stopped')}")
    except (OSError, ValueError):
        print("son okuma yok (servis henüz okumadı)")
    return 0


def cmd_idea(args) -> int:
    i = sw.add_idea(args.text, source="cli", paths=_sid(args))
    sw.log_event("idea", paths=_sid(args), id=i.id, source="cli")
    print(f"✓ {i.id}")
    return 0


def cmd_log(args) -> int:
    for e in sw.tail_log(args.n, _sid(args)):
        rest = {k: v for k, v in e.items() if k not in ("ts", "event")}
        print(f"{e.get('ts')}  {e.get('event'):<16} {json.dumps(rest, ensure_ascii=False)}")
    return 0


def cmd_summary(args) -> int:
    """Günlük özeti `log.jsonl` + depolardan kurup yazdırır (motorun günde bir yazdığıyla AYNI metin); `--save`
    `steward/daily/<tarih>.md`ye de yazar (ntfy gitmez)."""
    date = args.date or time.strftime("%Y-%m-%d")
    try:
        time.strptime(date, "%Y-%m-%d")
    except ValueError:
        print("hata: --date YYYY-MM-DD olmalı")
        return 1
    sid = _sid(args)
    text = sw.summary_text(date, args.lang or steward_config(sid).lang, sid)
    print(text, end="")
    if args.save:
        print(f"\n→ {sw.write_daily(date, text, sid)}")
    return 0


def cmd_persona(args) -> int:
    shared = str(load_settings().get("steward_persona_text") or "")
    sid = _sid(args)
    print(sw.persona_text(shared if sid == "default" else (steward_config(sid).persona_text or shared)))
    return 0


def _audit_cli(sid: str, event: str, **data: Any) -> None:
    """CLI'dan gelen ayar değişikliğinin denetim izi (panel `http_config` zaten `source=ui` yazıyor): kim değiştirdi sorusu
    (ör. ilerlet'in act'e alınması 2026-10-24) günlükten cevaplanabilsin. Çağıran: `COPS_NAME` (claudeops oturumu), cwd, ppid."""
    try:
        sw.log_event(event, paths=sid, source="cli", caller=os.environ.get("COPS_NAME") or "", cwd=os.getcwd(),
                     ppid=os.getppid(), **data)
    except Exception:
        pass


def cmd_config(args) -> int:
    """`steward.<alan>` ayarı: `py/cops steward config tick_seconds 90`; `-s SID` ile `stewards.<SID>.<alan>`. Makine geneli
    anahtar (`sw.MACHINE_KEYS`) kimlik bloğunda YOK SAYILIR: yazılmaz, uyarılır (default'a yazın)."""
    sid = _sid(args)
    field = args.key
    if field == "mode" and args.value not in sw.MODES:
        print(f"hata: mode {' | '.join(sw.MODES)} olmalı")
        return 1
    if field == "summary_hour" and not (args.value.isdigit() and 0 <= int(args.value) <= 23):
        print("hata: summary_hour 0-23 arası bir saat olmalı")
        return 1
    hidden = {"history_warn_at", "role"} | ({"sid", "brain_name"} if sid != "default" else set())   # rol yalnız `create --role`
    if field not in {f.name for f in dataclasses.fields(sw.Config)} or field in hidden:
        print("bilinmeyen alan; geçerli: " + ", ".join(f.name for f in dataclasses.fields(sw.Config) if f.name not in hidden))
        return 1
    if sid != "default" and field in sw.MACHINE_KEYS:
        print(f"uyarı: '{field}' MAKİNE GENELİ bir anahtar: stewards.{sid} içinde yok sayılır, YAZILMADI. "
              f"Makine geneli değer için: py/cops steward config {field} {args.value}  (default bloğu)")
        return 1
    old = getattr(steward_config(sid), field, None)
    if sid == "default":
        save_settings({"steward": {field: args.value}})
    else:
        save_settings({"stewards": {sid: {field: args.value}}})
    cfg = steward_config(sid)
    _audit_cli(sid, "config", key=field, old=old, value=getattr(cfg, field))
    print(f"✓ {'steward' if sid == 'default' else 'stewards.' + sid}.{field} = {getattr(cfg, field)!r}")
    return 0


def cmd_toggle(args) -> int:
    on = args.action == "on"
    if getattr(args, "all", False) and not on:     # `off --all`: tüm kimlikleri kapat
        for sid in steward_ids():
            save_settings({"steward": {"enabled": "off"}} if sid == "default" else {"stewards": {sid: {"enabled": "off"}}})
        print(f"✓ tüm değnekçiler KAPALI ({', '.join(steward_ids())}); beyin oturumları panel Durdur ile kapatılır")
        return 0
    sid = _sid(args)
    save_settings({"steward": {"enabled": "on" if on else "off"}} if sid == "default"
                  else {"stewards": {sid: {"enabled": "on" if on else "off"}}})
    _audit_cli(sid, "enable" if on else "disable")
    tag = "" if sid == "default" else f" [{sid}]"
    print(f"✓ değnekçi{tag} {'AÇIK' if on else 'KAPALI'} (panel çalışıyorsa bir sonraki tick'ten itibaren geçerli)")
    if on:
        if steward_config(sid).mode == "observe":
            print("  mod=observe: oturumlara DOKUNULMAZ, yapılacaklar `would:` olarak kaydedilir, günde bir özet gelir "
                  f"(act için: py/cops steward{_sflag(sid)} config mode act)")
        else:
            print("  mod=act: değnekçi oturumları açar/durdurur/direktif verir")
    return 0


# ── kimlik yönetimi (çoklu değnekçi P6) ───────────────────────────────────────

def cmd_list(args) -> int:
    ids = steward_ids()
    index = sw.ownership_index(ids)
    print(f"{'ID':<14}{'AÇIK':<7}{'MOD':<9}{'PROJE':>6}  {'BEYİN':<22}LABEL")
    for sid in ids:
        cfg = steward_config(sid)
        print(f"{sid:<14}{'açık' if cfg.enabled else 'kapalı':<7}{cfg.mode:<9}{len(sw.load_projects(sid)):>6}  "
              f"{cfg.brain_name:<22}{cfg.label}")
    if index.get("conflicts"):
        print("uyarı: sahiplik çakışması: " + ", ".join(f"{n} ({'/'.join(v)})" for n, v in sorted(index["conflicts"].items())))
    return 0


def cmd_create(args) -> int:
    sid = args.target_sid
    if not sw.valid_custom_id(sid):
        print(f"hata: geçersiz kimlik {sid!r}: ^[a-z]{{2,16}}$, rezerve değil ('default', 'all', ...), 'degnekci' ile başlamaz")
        return 1
    if sid in steward_ids():
        print(f"hata: '{sid}' zaten tanımlı")
        return 1
    role = getattr(args, "role", None) or "steward"
    if role not in sw.ROLES:
        print(f"hata: rol {' | '.join(sw.ROLES)} olmalı")
        return 1
    block = {"label": args.label or "", "enabled": "off", "mode": "observe"}
    if role != "steward":
        block["role"] = role        # rol YALNIZ yaratılırken verilir (`config` ile değişmez)
    save_settings({"stewards": {sid: block}})
    os.makedirs(sw.paths_for(sid).root, exist_ok=True)
    sw.log_event("create", paths=sid, label=args.label or "", role=role, source="cli")
    cfg = steward_config(sid)
    if cfg.role == "reviewer":
        print(f"✓ reviewer değnekçi '{sid}' oluşturuldu (KAPALI; beyin yok, proje sahibi olamaz, oturuma dokunmaz); "
              f"dizin: {sw.paths_for(sid).root}")
        print(f"  açmak için: py/cops steward -s {sid} on")
        return 0
    if cfg.role == "generic":
        print(f"✓ generic değnekçi '{sid}' oluşturuldu (KAPALI, mod={cfg.mode}, beyin={cfg.brain_name}, ana oturum "
              f"{cfg.planned_model} + {cfg.planned_effort}; beynin Opus/Fable/high isteği sahibin onayına bağlı); "
              f"dizin: {sw.paths_for(sid).root}")
        print(f"  proje ekle/çıkar: py/cops steward -s {sid} set PROJE --phase planned / drop PROJE   açmak için: py/cops steward -s {sid} on")
        return 0
    print(f"✓ değnekçi '{sid}' oluşturuldu (KAPALI, mod={cfg.mode}, beyin={cfg.brain_name}); dizin: {sw.paths_for(sid).root}")
    print(f"  proje devri: py/cops steward transfer PROJE {sid}   açmak için: py/cops steward -s {sid} on")
    return 0


def cmd_remove(args) -> int:
    sid = args.target_sid
    if sid == "default":
        print("hata: 'default' silinemez")
        return 1
    if sid not in steward_ids():
        print(f"hata: bilinmeyen değnekçi kimliği: {sid!r}")
        return 1
    brain = sw.brain_name_for(sid)
    try:
        brain_up = _project_running(brain)
    except Exception as e:
        print(f"uyarı: beyin oturumu denetimi yapılamadı ({e}); devam ediliyor")
        brain_up = False
    if brain_up:
        # Kimlik silinince çalışan beyni sahipsiz kalır (bu CLI süreci panelde değil: kapatamaz); önce panel Durdur.
        print(f"hata: '{sid}' kimliğinin beyin oturumu '{brain}' ÇALIŞIYOR; önce kapatın (panel Durdur), sonra silin")
        return 1
    with sw.ownership_lock():       # yeni proje talebi bu kilidi alır: kontrol ile taşıma arasında proje eklenemez
        names = sorted(sw.load_projects(sid))
        if names:
            print(f"hata: '{sid}' kimliğinin projesi var ({', '.join(names[:8])}{'…' if len(names) > 8 else ''}): "
                  f"önce devredin (py/cops steward transfer PROJE <başka-kimlik>)")
            return 1
        root = sw.paths_for(sid).root
        dest = ""
        if os.path.isdir(root):
            dest = os.path.join(os.path.dirname(root), ".removed", f"{sid}-{time.strftime('%Y%m%d_%H%M%S')}")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(root, dest)
    save_settings({"stewards": {sid: None}})
    print(f"✓ değnekçi '{sid}' silindi" + (f" (dizin: {dest})" if dest else "")
          + f"; beyin oturumu '{sw.brain_name_for(sid)}' çalışıyorsa panel Durdur ile kapatın")
    return 0


def _project_running(name: str) -> bool:
    from ..discovery import find_sessions
    return any(s.name == name for s in find_sessions(measure_cpu=False))


def cmd_transfer(args) -> int:
    target = args.to or args.target
    if not target:
        print("hata: hedef kimlik gerekli: py/cops steward transfer PROJE SID")
        return 1
    if target not in steward_ids():
        print(f"hata: bilinmeyen değnekçi kimliği: {target!r} (tanımlı: {', '.join(steward_ids())})")
        return 1
    if not args.force:
        try:
            if _project_running(args.project):
                print(f"hata: '{args.project}' oturumu ÇALIŞIYOR; önce kapatın (panel Durdur) ya da --force")
                return 1
        except Exception as e:
            print(f"uyarı: oturum denetimi yapılamadı ({e}); devam ediliyor")
    try:
        src = sw.transfer_project(args.project, target)
    except (ValueError, sw.LockTimeout) as e:
        print(f"hata: {e}")
        return 1
    print(f"✓ '{args.project}' {src} -> {target} devredildi (kayıt + açık/iletilmemiş sorular + bekleyen işler)")
    return 0


# ── pasif servis kaydı ve dış iş kuyruğu (çoklu değnekçi P8b) ─────────────────

def cmd_service(args) -> int:
    act = getattr(args, "svc_action", None) or "list"
    if act == "add":
        try:
            rec = sj.add_service(args.name, args.url, args.token_file, args.match, args.label or "")
        except (ValueError, sw.LockTimeout) as e:
            print(f"hata: {e}")
            return 1
        warn = sj.token_file_warning(sj.token_file_path(rec))
        print(f"✓ servis '{args.name}' kaydedildi ({rec['url']}, {rec['match']}): oturumlarına hiçbir değnekçi eylemi gitmez")
        if warn:
            print("uyarı: " + warn)
        return 0
    if act == "rm":
        try:
            ok = sj.remove_service(args.name)
        except sw.LockTimeout as e:
            print(f"hata: {e}")
            return 1
        print(f"✓ servis '{args.name}' silindi" if ok else f"hata: servis '{args.name}' kayıtlı değil")
        return 0 if ok else 1
    svcs = sj.load_services()
    if not svcs:
        print("kayıtlı servis yok (eklemek için: py/cops steward service add NAME --url URL --token-file PATH)")
        return 0
    print(f"{'AD':<14}{'EŞLEME':<8}URL")
    for n, r in sorted(svcs.items()):
        tf = sj.token_file_path(r)
        print(f"{n:<14}{r.get('match') or 'prefix':<8}{r.get('url')}   token: {tf or '-'}")
        warn = sj.token_file_warning(tf) if tf else ""
        if warn:
            print("  uyarı: " + warn)
        elif tf and not os.path.isfile(tf):
            print("  uyarı: token dosyası YOK")
    return 0


def _job_line(j: Dict[str, Any]) -> str:
    done = "iletildi" if j.get("delivered") else ("bekliyor" if sj.pending_stage(j) else "-")
    return (f"{str(j.get('service')) + '#' + str(j.get('id')):<16}{j.get('state') or '?':<18}{j.get('project') or '-':<14}"
            f"{j.get('kind') or '-':<20}{done:<9}{_ago(float(j.get('created_at') or 0))}")


def cmd_jobs(args) -> int:
    sid = _sid(args)
    act = getattr(args, "jobs_action", None) or "list"
    jobs = sj.load_jobs(sid)
    if act == "poll":
        if not jobs:
            print("iş kaydı yok")
            return 0
        res = sj.poll_jobs(sid, force=True)
        print(f"yoklandı: {res['polled']}  değişen: {res['changed']}  hata: {res['errors']}  atlanan: {res['skipped']}")
        return 0 if not res["errors"] else 1
    if act == "ack":
        j = sj.find_job(jobs, args.id)
        if j is None:
            print(f"hata: iş bulunamadı: {args.id}")
            return 1
        if j.get("state") not in sj.TERMINAL_STATES:
            # Açık (ya da bilinmeyen durumlu) işe ack: `delivered` yazılırsa iş bitince sonuç proje oturumuna HİÇ gitmezdi.
            print(f"hata: iş {j.get('service')}#{j['id']} henüz açık ({j.get('state') or '?'}); "
                  f"yalnız bitmiş/başarısız/iptal/kayıp iş iletildi sayılabilir")
            return 1
        sj.mark_delivered(j["id"], j.get("service") or "", "result", paths=sid)      # yerel: varaka'ya YAZILMAZ
        print(f"✓ iş {j.get('service')}#{j['id']} iletildi sayıldı (yerel işaret)")
        return 0
    if act == "show":
        j = sj.find_job(jobs, args.id)
        if j is None:
            print(f"hata: iş bulunamadı: {args.id}")
            return 1
        print(json.dumps(j, ensure_ascii=False, indent=2))
        return 0
    rows = jobs if getattr(args, "all", False) else [j for j in jobs if sj.is_open(j) or sj.pending_stage(j)]
    if getattr(args, "state", None):
        rows = [j for j in jobs if j.get("state") == args.state]
    if not rows:
        print("iş yok" if not jobs else "açık/iletilmemiş iş yok (hepsi için: --all)")
        return 0
    print(f"{'İŞ':<16}{'DURUM':<18}{'PROJE':<14}{'TÜR':<20}{'İLETİM':<9}YAŞ")
    for j in sorted(rows, key=lambda x: -float(x.get("created_at") or 0)):
        print(_job_line(j))
    return 0


def _get(port: int, path: str, sid: str, **q: str) -> Dict[str, Any]:
    import urllib.parse
    qq = {k: v for k, v in dict(q, steward=("" if sid == "default" else sid)).items() if v}
    return _api(port, "GET", path + ("?" + urllib.parse.urlencode(qq) if qq else ""), None)


def cmd_review(args) -> int:
    """reviewer kimliği: status|pool add|rm|on|off PROJE|run PROJE [mode/model]|cancel [PROJE]|history|findings."""
    port, sid = args.port, _sid(args)
    act = getattr(args, "review_action", None) or "status"
    if act == "pool":
        verb = {"add": "add", "rm": "remove", "on": "enable", "off": "disable"}[args.pool_action]
        res = _api(port, "POST", "/api/steward/review/pool", {"action": verb, "project": args.project}, sid)
        print(f"✓ havuz {verb}: {args.project}" if res.get("ok") else f"hata: {res.get('error')}")
        return 0 if res.get("ok") else 1
    if act == "run":
        mode, model = "", ""
        if getattr(args, "target", ""):
            mode, _, model = args.target.partition("/")
            if not mode or not model:
                print("hata: hedef <mode>/<model> biçiminde olmalı (ör. evren/glm-4.6)")
                return 1
        res = _api(port, "POST", "/api/steward/review/run", {"project": args.project, "mode": mode, "model": model}, sid)
        print(f"✓ başladı: {res.get('key')}" if res.get("ok") else f"hata: {res.get('error')}")
        return 0 if res.get("ok") else 1
    if act == "cancel":
        res = _api(port, "POST", "/api/steward/review/cancel", {"project": getattr(args, "project", "") or ""}, sid)
        print(f"iptal edilen: {', '.join(res.get('cancelled') or []) or '-'}" if res.get("ok") else f"hata: {res.get('error')}")
        return 0 if res.get("ok") else 1
    if act == "verify":
        body: Dict[str, Any] = {"project": args.project}
        if getattr(args, "fid", None):
            body["fids"] = list(args.fid)
        res = _api(port, "POST", "/api/steward/review/verify", body, sid)
        if res.get("ok"):
            print(f"✓ doğrulama gönderildi: {res.get('session')} ({len(res.get('findings') or [])} bulgu, sahip {res.get('owner')})")
            return 0
        print(f"hata: {res.get('error')}")
        return 1
    if act in ("approve", "reject"):
        res = _api(port, "POST", "/api/steward/review/finding", {"id": args.fid, "action": act}, sid)
        print(f"✓ {args.fid}: {res.get('state')}" if res.get("ok") else f"hata: {res.get('error')}")
        return 0 if res.get("ok") else 1
    if act == "export":
        res = _api(port, "POST", "/api/steward/review/export", {"project": args.project, "kind": args.kind}, sid)
        if res.get("ok"):
            print(f"✓ {res.get('file')}: yazılan {len(res.get('written') or [])}, zaten vardı {len(res.get('already') or [])}")
            return 0
        print(f"hata: {res.get('error')}")
        return 1
    if act == "findings":
        res = _get(port, "/api/steward/review/findings", sid, project=getattr(args, "project", "") or "",
                   state=getattr(args, "state", "") or "")
        if not res.get("ok"):
            print(f"hata: {res.get('error')}")
            return 1
        rows = res.get("findings") or []
        for f in rows:
            print(f"{f.get('severity'):<3} {f.get('state'):<11} {f.get('project'):<14} {f.get('ref'):<6} {f.get('where')}  {f.get('title')}")
        if not rows:
            print("bulgu yok")
        return 0
    res = _get(port, "/api/steward/review/state", sid)
    if not res.get("ok"):
        print(f"hata: {res.get('error')}")
        return 1
    if act == "history":
        for r in res.get("runs") or []:
            print(f"{_ago(float(r.get('at') or 0)):<10} {r.get('status'):<15} {r.get('pair')}  {r.get('file') or ''}")
        if not res.get("runs"):
            print("çalıştırma kaydı yok")
        return 0
    tg = res.get("targets") or []
    print(f"reviewer: {'AÇIK' if res.get('enabled') else 'KAPALI'}  hedef={len(tg)}  çalışan={', '.join(res.get('running') or []) or '-'}")
    for r in res.get("pool") or []:
        done = sum(1 for p in (r.get("pairs") or {}).values() if isinstance(p, dict) and p.get("status") == "done")
        flag = "tamam" if r.get("complete") else f"{done}/{len(tg)}"
        print(f"  {'+' if r.get('enabled') else '-'} {r.get('project'):<16} {r.get('source'):<7} {flag}")
    if not res.get("pool"):
        print("havuz boş")
    return 0


def cmd_up(args) -> int:
    """Tek komutla açma: `on` + `close`'un yorumladığı (`# CLOSED`) proje satırlarını geri aç + beyni başlat. Bekleyen
    cevapları ayrıca iletmek gerekmez: ilk tick `deliver_answer` ile iletir."""
    from . import close as close_cmd
    rc = cmd_toggle(types.SimpleNamespace(action="on", all=False, sid=args.sid))
    if rc:
        return rc
    sid = args.sid
    paths = sw.paths_for(sid)
    for name in sorted(sw.load_projects(paths)):
        res = close_cmd.uncomment_models(name, dry_run=args.dry_run)
        if res == "restored":
            print(f"  models.tsv: {name} geri açıldı" + (" (kuru çalıştırma)" if args.dry_run else ""))
    if args.dry_run or args.no_brain:
        return 0
    res = _api(args.port, "POST", "/api/steward/brain", {"action": "start"}, sid)
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


def cmd_panic(args) -> int:
    """Acil durdurma: `on` = tüm kimlikler observe gibi (oturumlara direktif/devir/başlatma/durdurma yok), `off` = kaldır,
    `status`. Dosya (`steward/PANIC`) doğrudan yazılır: web servisi yanıt vermese de çalışır."""
    from .. import steward as _sw
    try:
        if args.panic_action == "on":
            _sw.set_panic(True, args.reason or "cli")
        elif args.panic_action == "off":
            _sw.set_panic(False)
    except OSError as e:
        print(f"hata: {e}", file=sys.stderr)
        return 1
    print("ACİL DURDURMA: " + ("AÇIK (tüm kimlikler observe gibi)" if _sw.panic_active() else "kapalı"))
    return 0


def cmd_shutdown(args) -> int:
    """Kontrollü kapatma: döngü kapanır; sonra servis (web) her tick'te proje oturumlarını SIRAYLA bitirir: iş sessizleşince
    devir mesajı → asistan "READY FOR HANDOVER" deyince durdur → en sonda beyin. İş bitmeyen/cevap vermeyen oturum
    AÇIK bırakılır. `--status` ilerlemeyi gösterir; `py/cops steward up` geri açar."""
    body: dict = {"status": True} if args.status else {}
    keep = [n for n in (args.keep or "").split(",") if n.strip()]
    if keep:
        body["modes"] = {n.strip(): "keep" for n in keep}
    only = [n.strip() for n in (getattr(args, "only", "") or "").split(",") if n.strip()]
    if only and not args.status:
        body["only"] = only
    res = _api(args.port, "POST", "/api/steward/shutdown", body, args.sid)
    if not res.get("ok"):
        print(json.dumps(res, ensure_ascii=False))
        return 1
    if args.status or res.get("already"):
        sd = res.get("shutdown") or {}
        items = {n: i.get("stage") for n, i in (sd.get("items") or {}).items()}
        print(("BİTTİ" if sd.get("done") else "SÜRÜYOR" if sd else "yok") + f": {items}")
    else:
        print("✓ kapatma başladı" + (" (yalnız " + ",".join(only) + "; döngü açık)" if only else " (döngü kapalı)") + "; ilerleme: py/cops steward shutdown --status (tick başına bir adım)")
    return 0


def cmd_api(args) -> int:
    port = args.port
    sid = _sid(args)
    if args.action == "tick":
        res = _api(port, "POST", "/api/steward/tick", {}, sid)
    elif args.action == "tour":
        res = _api(port, "POST", "/api/steward/tour", {}, sid)
    elif args.action == "brain":
        what = args.what or "status"
        if what == "status":
            # Yalnız okur: hiçbir şey başlatmaz/göndermez (eskiden argümansız `brain` beyni BAŞLATIYORDU, TODO 1233)
            cfg = steward_config(sid)
            running = _project_running(cfg.brain_name)
            print(f"beyin {cfg.brain_name}: {'çalışıyor' if running else 'çalışmıyor'}  "
                  f"({cfg.brain_cli} {cfg.brain_model or 'varsayılan'} {cfg.brain_effort}); "
                  f"başlatmak için: py/cops steward{_sflag(sid)} brain start")
            return 0
        res = _api(port, "POST", "/api/steward/brain", {"action": what}, sid)
    elif args.action == "directive":
        res = _api(port, "POST", "/api/steward/directive", {"name": args.name, "text": args.text or "",
                                                            "model": args.model or "", "effort": args.effort or "",
                                                            "reason": "cli"}, sid)
    elif args.action == "restart":
        res = _api(port, "POST", "/api/steward/restart", {"name": args.name, "text": args.text or "",
                                                          "model": args.model or "", "effort": args.effort or "",
                                                          "reason": args.reason or "cli"}, sid)
    else:
        res = {"ok": False, "error": "unknown action"}
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 1


def register(sub):
    p = sub.add_parser("steward", help="değnekçi: projeleri gezip iş veren zamanlayıcı (durum/proje/soru/fikir/tick)")
    p.add_argument("-s", "--steward", default=None, metavar="SID",
                   help=f"değnekçi kimliği (yoksa {ENV_STEWARD} ortam değişkeni, o da yoksa default)")
    s = p.add_subparsers(dest="action", metavar="<alt-komut>")

    s.add_parser("list", help="kimlikler (açık/kapalı, kip, proje sayısı, beyin)").set_defaults(func=cmd_list)
    pcr = s.add_parser("create", help="yeni değnekçi kimliği (varsayılan KAPALI + observe)")
    pcr.add_argument("target_sid", metavar="SID")
    pcr.add_argument("--label", default="")
    pcr.add_argument("--role", default="steward", choices=sw.ROLES,
                     help="steward (varsayılan) | reviewer (projesiz, beyinsiz, oturuma dokunmaz) | generic (dinamik "
                          "projeler, Sonnet medium, üst model sahibin onayıyla); yalnız yaratılırken")
    pcr.set_defaults(func=cmd_create)
    prm = s.add_parser("remove", help="kimliği sil (projesi varsa reddedilir)")
    prm.add_argument("target_sid", metavar="SID")
    prm.set_defaults(func=cmd_remove)
    ptr = s.add_parser("transfer", help="projeyi başka kimliğe devret (oturum kapalıyken)")
    ptr.add_argument("project")
    ptr.add_argument("target", nargs="?", default="", metavar="SID")
    ptr.add_argument("--to", default="", metavar="SID", help="hedef kimlik (konumsal SID ile aynı)")
    ptr.add_argument("--force", action="store_true", help="oturum çalışıyor denetimini atla")
    ptr.set_defaults(func=cmd_transfer)

    psv = s.add_parser("service", help="pasif paylaşımlı servis kaydı (varaka): add|rm|list (makine geneli, yalnız insan)")
    sv = psv.add_subparsers(dest="svc_action", metavar="<add|rm|list>")
    sva = sv.add_parser("add", help="servis ekle (token DOSYASI yolu; token argv'ye girmez)")
    sva.add_argument("name")
    sva.add_argument("--url", required=True, help="kök adres, ör. http://127.0.0.1:8080")
    sva.add_argument("--token-file", required=True, help="Bearer token dosyası (chmod 600)")
    sva.add_argument("--match", choices=["prefix", "exact"], default="prefix", help="oturum adı eşlemesi (varsayılan prefix)")
    sva.add_argument("--label", default="")
    svr = sv.add_parser("rm", help="servis kaydını sil")
    svr.add_argument("name")
    sv.add_parser("list", help="kayıtlı servisler")
    psv.set_defaults(func=cmd_service)
    pjb = s.add_parser("jobs", help="dış iş kuyruğu (varaka) kayıtları: list|show ID|poll|ack ID")
    jb = pjb.add_subparsers(dest="jobs_action", metavar="<list|show|poll|ack>")
    jbl = jb.add_parser("list", help="açık/iletilmemiş işler")
    jbl.add_argument("--all", action="store_true")
    jbl.add_argument("--state", default="")
    jbs = jb.add_parser("show", help="bir işin tam kaydı")
    jbs.add_argument("id")
    jb.add_parser("poll", help="açık işleri şimdi yokla (panel gerekmez)")
    jba = jb.add_parser("ack", help="sonucu iletildi say (yerel işaret; varaka'ya yazılmaz)")
    jba.add_argument("id")
    pjb.set_defaults(func=cmd_jobs)
    pst = s.add_parser("status", help="özet")
    pst.add_argument("--port", type=int, default=mcp_queue.DEFAULT_PORT, help="uzak host sağlığı için panel portu")
    pst.set_defaults(func=cmd_status)
    pp = s.add_parser("projects", help="proje listesi")
    pp.add_argument("--phase", choices=sw.PHASES, default=None)
    pp.set_defaults(func=cmd_projects)
    ps = s.add_parser("set", help="proje kaydını ekle/güncelle")
    ps.add_argument("name")
    ps.add_argument("--phase", choices=sw.PHASES)
    ps.add_argument("--kind", choices=sw.KINDS)
    ps.add_argument("--goal")
    ps.add_argument("--priority", type=int)
    ps.add_argument("--cadence", type=int, metavar="MIN", help="en az bu sıklıkta uğra (0 = elle)")
    ps.add_argument("--note")
    ps.add_argument("--model")
    ps.add_argument("--effort")
    ps.add_argument("--host", default=None, metavar="HOST",
                    help="oturumun çalıştığı host (hosts.json adı; local = yerel). Panel üzerinden yazılır")
    ps.add_argument("--force", action="store_true", help="--host: çalışan oturum denetimini atla")
    ps.add_argument("--port", type=int, default=mcp_queue.DEFAULT_PORT)
    ps.set_defaults(func=cmd_set)
    pdr = s.add_parser("drop", help="projeyi kimliğin kaydından çıkar (oturuma/roster'a dokunmaz)")
    pdr.add_argument("name")
    pdr.set_defaults(func=cmd_drop)
    pk = s.add_parser("cards", help="proje kartları (hedef / sıradaki adım / açık TBD / engel)")
    pk.add_argument("name", nargs="?", default="")
    pk.add_argument("--refresh", action="store_true", help="şimdi yenile (panel çalışıyor olmalı; ad verilmezse yenilemesi gerekenlerin hepsi)")
    pk.add_argument("--port", type=int, default=mcp_queue.DEFAULT_PORT)
    pk.set_defaults(func=cmd_cards)
    pi = s.add_parser("import", help="roster'daki projeleri değnekçiye toplu kaydet")
    pi.add_argument("--phase", choices=sw.PHASES, default="planned")
    pi.add_argument("--cadence", type=int, default=240, metavar="MIN")
    pi.set_defaults(func=cmd_import)
    pq = s.add_parser("questions", help="sorular")
    pq.add_argument("--all", action="store_true")
    pq.set_defaults(func=cmd_questions)
    pa = s.add_parser("answer", help="soruyu cevapla (seçenekli soruda numara da olur)")
    pa.add_argument("id")
    pa.add_argument("answer")
    pa.set_defaults(func=cmd_answer)
    pask = s.add_parser("ask", help="soru aç (panel üzerinden: telefona bildirim + /q/<id> bağlantısı)")
    pask.add_argument("text")
    pask.add_argument("-p", "--project", default="")
    pask.add_argument("-o", "--option", action="append", help="seçenek (tekrarlanabilir, en çok 6)")
    pask.add_argument("--port", type=int, default=mcp_queue.DEFAULT_PORT)
    pask.set_defaults(func=cmd_ask)
    pd = s.add_parser("ideas", help="fikir kutusu")
    pd.add_argument("--all", action="store_true")
    pd.set_defaults(func=cmd_ideas)
    pq = s.add_parser("quota", help="kota bekçisi: haftalık plan kullanımına göre yeni işi kes (drain) ya da hepsini durdur")
    pq.add_argument("quota_action", choices=("status", "check", "mode", "limit", "shutdown", "final", "poll", "day"))
    pq.add_argument("value", nargs="?", default="")
    pq.add_argument("more", nargs="*")
    pq.set_defaults(func=cmd_quota)
    ppc = s.add_parser("panic", help="ACİL DURDURMA: tüm değnekçi kimlikleri observe gibi (oturuma dokunma yok); on|off|status")
    ppc.add_argument("panic_action", choices=("on", "off", "status"), nargs="?", default="status")
    ppc.add_argument("--reason", default="")
    ppc.set_defaults(func=cmd_panic)
    pn = s.add_parser("idea", help="fikir ekle")
    pn.add_argument("text")
    pn.set_defaults(func=cmd_idea)
    pm = s.add_parser("summary", help="günlük özet (tick/eylem/would/soru/fikir/kart/handover/bekleyen)")
    pm.add_argument("--date", default="", metavar="YYYY-MM-DD", help="varsayılan: bugün")
    pm.add_argument("--lang", choices=["tr", "en"], default="")
    pm.add_argument("--save", action="store_true", help="steward/daily/<tarih>.md'ye de yaz")
    pm.set_defaults(func=cmd_summary)
    pl = s.add_parser("log", help="son olaylar")
    pl.add_argument("-n", type=int, default=50)
    pl.set_defaults(func=cmd_log)
    s.add_parser("persona", help="etkin persona metni").set_defaults(func=cmd_persona)
    pc = s.add_parser("config", help="steward.<alan> ayarını yaz (tick_seconds, max_active, brain_model, ...)")
    pc.add_argument("key")
    pc.add_argument("value")
    pc.set_defaults(func=cmd_config)
    psd = s.add_parser("shutdown", help="kontrollü kapatma: kapat → işi bitir → devir → durdur (önce projeler, sonra beyin)")
    psd.add_argument("--port", type=int, default=mcp_queue.DEFAULT_PORT)
    psd.add_argument("--status", action="store_true")
    psd.add_argument("--keep", default="", help="virgüllü oturum adları: devir alınır ama oturum AÇIK kalır (yalnız dur)")
    psd.add_argument("--only", default="", help="virgüllü PROJE adları: yalnız bunlar kapatılır (paused; iş biter, devir, durdur); döngü ve diğer projeler sürer")
    psd.set_defaults(func=cmd_shutdown)
    pup = s.add_parser("up", help="tek komutla aç: on + models.tsv'de # CLOSED satırlarını geri aç + beyni başlat")
    pup.add_argument("--port", type=int, default=mcp_queue.DEFAULT_PORT)
    pup.add_argument("--dry-run", action="store_true", help="models.tsv'ye yazma, beyni başlatma (yalnız on yapılır)")
    pup.add_argument("--no-brain", action="store_true")
    pup.set_defaults(func=cmd_up)
    prv = s.add_parser("review", help="reviewer kimliği: status|pool add|rm|on|off PROJE|run PROJE [mode/model]|cancel [PROJE]|history|findings|verify PROJE|approve|reject FID|export PROJE")
    prv.add_argument("--port", type=int, default=mcp_queue.DEFAULT_PORT)
    rv_ = prv.add_subparsers(dest="review_action", metavar="<alt>")
    rv_.add_parser("status", help="havuz + hedefler + çalışan iş")
    rv_.add_parser("history", help="son çalıştırmalar")
    rpl = rv_.add_parser("pool", help="havuz: add|rm|on|off PROJE")
    rpl.add_argument("pool_action", choices=["add", "rm", "on", "off"])
    rpl.add_argument("project")
    rru = rv_.add_parser("run", help="elle başlat: PROJE [mode/model]")
    rru.add_argument("project")
    rru.add_argument("target", nargs="?", default="", help="<mode>/<model>, ör. evren/glm-4.6 (yoksa sıradaki hedef)")
    rca = rv_.add_parser("cancel", help="koşan işi iptal et (PROJE yoksa hepsi)")
    rca.add_argument("project", nargs="?", default="")
    rfi = rv_.add_parser("findings", help="bulgular")
    rfi.add_argument("--project", default="")
    rfi.add_argument("--state", default="")
    rve = rv_.add_parser("verify", help="bulguları projenin kendi oturumuna doğrulat (Sonnet alt ajan): PROJE [--fid ID]...")
    rve.add_argument("project")
    rve.add_argument("--fid", action="append", default=[], help="yalnız bu bulgu(lar); yoksa projenin yeni bulguları")
    for verb, h in (("approve", "bulguyu onayla (yalnız verified|unclear)"), ("reject", "bulguyu reddet")):
        rde = rv_.add_parser(verb, help=h)
        rde.add_argument("fid")
    rex = rv_.add_parser("export", help="onaylı bulguları projenin TODO.md/TOBEDECIDED.md dosyasına yaz: PROJE [--kind todo|tbd]")
    rex.add_argument("project")
    rex.add_argument("--kind", choices=["todo", "tbd"], default="todo")
    prv.set_defaults(func=cmd_review)
    s.add_parser("on", help="döngüyü aç (steward.enabled=on)").set_defaults(func=cmd_toggle)
    poff = s.add_parser("off", help="döngüyü kapat (--all: tüm kimlikleri)")
    poff.add_argument("--all", action="store_true")
    poff.set_defaults(func=cmd_toggle)
    for name, helptext in (("tick", "bir tick çalıştır (panel üzerinden)"), ("tour", "beyne şimdi bir tur gönder"),
                           ("brain", "beyin oturumu: status (varsayılan, yalnız okur) | start | stop"), ("directive", "NAME'e direktif gönder"),
                           ("restart", "NAME'i durdur + yeni direktifle aç")):
        px = s.add_parser(name, help=helptext)
        px.add_argument("--port", type=int, default=mcp_queue.DEFAULT_PORT)
        if name == "brain":
            px.add_argument("what", nargs="?", choices=["status", "start", "stop"], default="status",
                            help="status: yalnız durumu göster (varsayılan, hiçbir şey başlatmaz); "
                                 "start: beyni başlat; stop: beyni durdur")
        if name in ("directive", "restart"):
            px.add_argument("name")
            px.add_argument("text", nargs="?", default="")
            px.add_argument("--model")
            px.add_argument("--effort")
            px.add_argument("--reason")
        px.set_defaults(func=cmd_api)
    for sp in s.choices.values():      # alt-komut `func`ı doğrudan çağrılır (`run` yalnız alt-komutsuz): kimliği HER BİRİNDE çöz
        sp.set_defaults(func=_with_sid(sp.get_default("func")))
    p.set_defaults(func=run)


def _with_sid(fn):
    def wrapped(args) -> int:
        try:
            args.sid = resolve_sid(args)
        except ValueError as e:
            print(f"hata: {e}")
            return 1
        return fn(args)
    return wrapped


def run(args) -> int:
    """Alt-komutsuz `py/cops steward` = status."""
    return _with_sid(cmd_status)(args)
