"""`steward` (değnekçi) — projeleri gezen zamanlayıcının insan tarafı.

Kullanım:
  py/cops steward status                      # özet: açık/kapalı, projeler faz faz, açık sorular, son tick
  py/cops steward projects [--phase planned]  # proje listesi
  py/cops steward cards [NAME] [--refresh]    # proje kartları (NAME: tek kartın tamamı); --refresh: şimdi yenile (panel üzerinden)
  py/cops steward set NAME [--phase planning] [--kind book] [--goal "..."] [--priority 2]
                           [--cadence 240] [--note "..."] [--model m] [--effort e]
  py/cops steward import [--phase planned]    # roster'daki (değnekçide olmayan) projeleri toplu kaydet
  py/cops steward questions [--all]           # bana sorulanlar
  py/cops steward answer ID "cevap"           # cevapla (motor oturuma iletir)
  py/cops steward ideas [--all] / idea "metin"
  py/cops steward summary [--date YYYY-MM-DD] [--lang tr|en] [--save]   # günlük özet (log.jsonl'dan; panel gerekmez)
  py/cops steward log [-n 50]
  py/cops steward persona                     # etkin persona metni
  py/cops steward on|off / config KEY VALUE   # döngüyü aç-kapat / steward.<alan> ayarı (tick_seconds, max_active...)
  py/cops steward tick / tour / brain start|stop / directive NAME "metin" / restart NAME "direktif" --reason "..."
                                               (panel çalışıyor olmalı: /api/steward/* üzerinden)

Depo/ayar dosyaları: ~/.claude/claudeops/steward/ ve settings.json'daki `steward` alanı
(`py/cops config` ya da panel Ayarlar). Döngü yalnız `steward.enabled=on` iken kendiliğinden tick atar.
"""
from __future__ import annotations
import dataclasses
import json
import time
from typing import Any, Dict

from .. import roster as roster_mod
from .. import steward as sw
from ..settings import load_settings, save_settings, steward_config
from . import mcp_queue

PHASE_ICON = {"idea": "💡", "planning": "📐", "planned": "🛠", "paused": "⏸", "done": "✅"}


def _api(port: int, method: str, path: str, body: Dict[str, Any] | None = None) -> Dict[str, Any]:
    try:
        return mcp_queue._api(port, method, path, body)
    except mcp_queue.ApiError as e:
        return {"ok": False, "error": str(e)}


def _ago(ts: float) -> str:
    if not ts:
        return "-"
    d = int(time.time() - ts)
    return f"{d // 86400}g" if d >= 86400 else f"{d // 3600}s" if d >= 3600 else f"{d // 60}dk"


def cmd_status(args) -> int:
    cfg = steward_config()
    projects = sw.load_projects()
    qs = sw.open_questions()
    ideas = [i for i in sw.load_ideas() if i.status == "new"]
    st = sw.load_state()
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
    for q in qs[:5]:
        print(f"  ? [{q.id}] {q.project or '-'}: {q.text[:120]}")
    if not cfg.enabled:
        print("\naçmak için: py/cops steward on   (ya da panel Ayarlar) — hiçbir şey kendiliğinden başlamaz")
    return 0


def cmd_projects(args) -> int:
    projects = sw.load_projects()
    rows = sorted(projects.values(), key=lambda p: (p.priority, p.phase, p.name))
    if args.phase:
        rows = [p for p in rows if p.phase == args.phase]
    if not rows:
        print("değnekçi projesi yok — `py/cops steward import` roster'dakileri alır, `set NAME --phase ...` tek tek ekler")
        return 0
    cards = sw.load_cards()
    print(f"{'NAME':<24}{'PHASE':<10}{'P':>2} {'CAD':>5} {'VISIT':>6}  NEXT / GOAL")
    for p in rows:
        nxt = sw.card_one_liner(cards.get(p.name)) or p.goal
        print(f"{p.name:<24}{p.phase:<10}{p.priority:>2} {p.cadence_minutes:>5} {_ago(p.last_visit):>6}  {nxt[:70]}")
    return 0


def cmd_cards(args) -> int:
    """Kartları listele / tek kartı göster (dosyadan, panel gerekmez); `--refresh` panele yenileme işi bırakır."""
    if args.refresh:
        res = _api(args.port, "POST", "/api/steward/cards/refresh", {"name": args.name or ""})
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
    projects = sw.load_projects()
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
    try:
        p = sw.upsert_project(args.name, **{k: v for k, v in fields.items() if v is not None})
    except ValueError as e:
        print(f"hata: {e}")
        return 1
    sw.log_event("project_set", name=p.name, fields=[k for k, v in fields.items() if v is not None], source="cli")
    print(json.dumps(dataclasses.asdict(p), ensure_ascii=False, indent=2))
    if p.name not in {e.name for e in roster_mod.read_roster()}:
        print(f"uyarı: '{p.name}' roster'da yok — değnekçi oturum açamaz. Panelden kaydet ya da beyne "
              f"steward_register_project yaptır (klasör + GOAL.md + roster).")
    return 0


def cmd_import(args) -> int:
    projects = sw.load_projects()
    added = 0
    for e in roster_mod.read_roster():
        if e.name in projects or not sw.valid_name(e.name):
            continue
        sw.upsert_project(e.name, phase=args.phase, cadence_minutes=args.cadence)
        added += 1
    print(f"{added} proje eklendi (faz={args.phase}, cadence={args.cadence} dk); amaç/tür için: py/cops steward set NAME --goal ...")
    return 0


def cmd_questions(args) -> int:
    qs = sw.load_questions() if args.all else sw.open_questions()
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
               {"project": args.project or "", "text": args.text, "options": args.option or [], "source": "cli"})
    if not res.get("ok"):
        print(f"hata: {res.get('error')}")
        return 1
    print(f"✓ soru [{res['id']}] " + ("bildirildi" if res.get("notified") else "kaydedildi (ntfy yok ya da zaten bildirilmişti)")
          + (f"\n  {res['link']}" if res.get("link") else "  (tünel adresi yok: bağlantı üretilmedi)"))
    return 0


def cmd_answer(args) -> int:
    try:
        q = sw.answer_question(args.id, args.answer)
    except ValueError as e:
        print(f"hata: {e}")
        return 1
    if q is None:
        print("bilinmeyen soru id'si")
        return 1
    sw.log_event("answer", id=q.id, project=q.project, source="cli")
    print(f"✓ cevaplandı — motor bir sonraki tick'te {q.project or 'beyne'} iletir (hemen: py/cops steward tick)")
    return 0


def cmd_ideas(args) -> int:
    ideas = sw.load_ideas() if args.all else [i for i in sw.load_ideas() if i.status == "new"]
    if not ideas:
        print("fikir yok")
        return 0
    for i in ideas:
        print(f"[{i.id}] {i.status:<7} {i.project or '-':<16} {i.text[:140]}")
    return 0


def cmd_idea(args) -> int:
    i = sw.add_idea(args.text, source="cli")
    sw.log_event("idea", id=i.id, source="cli")
    print(f"✓ {i.id}")
    return 0


def cmd_log(args) -> int:
    for e in sw.tail_log(args.n):
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
    text = sw.summary_text(date, args.lang or steward_config().lang)
    print(text, end="")
    if args.save:
        print(f"\n→ {sw.write_daily(date, text)}")
    return 0


def cmd_persona(args) -> int:
    print(sw.persona_text(str(load_settings().get("steward_persona_text") or "")))
    return 0


def cmd_config(args) -> int:
    """`steward.<alan>` ayarı: `py/cops steward config tick_seconds 90`; `on`/`off` = enabled."""
    field = args.key
    if field == "mode" and args.value not in sw.MODES:
        print(f"hata: mode {' | '.join(sw.MODES)} olmalı")
        return 1
    if field == "summary_hour" and not (args.value.isdigit() and 0 <= int(args.value) <= 23):
        print("hata: summary_hour 0-23 arası bir saat olmalı")
        return 1
    if field not in {f.name for f in dataclasses.fields(sw.Config)} or field == "history_warn_at":
        print("bilinmeyen alan; geçerli: " + ", ".join(f.name for f in dataclasses.fields(sw.Config) if f.name != "history_warn_at"))
        return 1
    save_settings({"steward": {field: args.value}})
    cfg = steward_config()
    print(f"✓ steward.{field} = {getattr(cfg, field)!r}")
    return 0


def cmd_toggle(args) -> int:
    save_settings({"steward": {"enabled": "on" if args.action == "on" else "off"}})
    print(f"✓ değnekçi {'AÇIK' if args.action == 'on' else 'KAPALI'} (panel çalışıyorsa bir sonraki tick'ten itibaren geçerli)")
    if args.action == "on":
        if steward_config().mode == "observe":
            print("  mod=observe: oturumlara DOKUNULMAZ, yapılacaklar `would:` olarak kaydedilir, günde bir özet gelir "
                  "(act için: py/cops steward config mode act)")
        else:
            print("  mod=act: değnekçi oturumları açar/durdurur/direktif verir")
    return 0


def cmd_api(args) -> int:
    port = args.port
    if args.action == "tick":
        res = _api(port, "POST", "/api/steward/tick", {})
    elif args.action == "tour":
        res = _api(port, "POST", "/api/steward/tour", {})
    elif args.action == "brain":
        res = _api(port, "POST", "/api/steward/brain", {"action": args.what or "start"})
    elif args.action == "directive":
        res = _api(port, "POST", "/api/steward/directive", {"name": args.name, "text": args.text or "",
                                                            "model": args.model or "", "effort": args.effort or "",
                                                            "reason": "cli"})
    elif args.action == "restart":
        res = _api(port, "POST", "/api/steward/restart", {"name": args.name, "text": args.text or "",
                                                          "model": args.model or "", "effort": args.effort or "",
                                                          "reason": args.reason or "cli"})
    else:
        res = {"ok": False, "error": "unknown action"}
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 1


def register(sub):
    p = sub.add_parser("steward", help="değnekçi: projeleri gezip iş veren zamanlayıcı (durum/proje/soru/fikir/tick)")
    s = p.add_subparsers(dest="action", metavar="<alt-komut>")

    s.add_parser("status", help="özet").set_defaults(func=cmd_status)
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
    ps.set_defaults(func=cmd_set)
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
    s.add_parser("on", help="döngüyü aç (steward.enabled=on)").set_defaults(func=cmd_toggle)
    s.add_parser("off", help="döngüyü kapat").set_defaults(func=cmd_toggle)
    for name, helptext in (("tick", "bir tick çalıştır (panel üzerinden)"), ("tour", "beyne şimdi bir tur gönder"),
                           ("brain", "beyin oturumu: start|stop"), ("directive", "NAME'e direktif gönder"),
                           ("restart", "NAME'i durdur + yeni direktifle aç")):
        px = s.add_parser(name, help=helptext)
        px.add_argument("--port", type=int, default=mcp_queue.DEFAULT_PORT)
        if name == "brain":
            px.add_argument("what", nargs="?", choices=["start", "stop"], default="start")
        if name in ("directive", "restart"):
            px.add_argument("name")
            px.add_argument("text", nargs="?", default="")
            px.add_argument("--model")
            px.add_argument("--effort")
            px.add_argument("--reason")
        px.set_defaults(func=cmd_api)
    p.set_defaults(func=run)


def run(args) -> int:
    if getattr(args, "action", None) is None:
        return cmd_status(args)
    return args.func(args)
