"""TOBEDECIDED#15 — controller/worker/decider orchestration, pure core.

Sadece dataclass'lar + `resolve_outcome()` + prompt-üretimi — hiç tmux/HTTP/
thread yok, bu yüzden sıfır canlı CLI'yla unit-test edilebilir. Asıl
dispatch/wait/persist motoru `commands/web_orch.py`'de.

Phase 2 (2026-09-10): controller (briefing/handoff) + decider rolleri
bağlandı. `resolve_outcome(has_decider=True)` KASITLI OLARAK hâlâ bir
no-op stub — decider'ın kendi verdict'i kazandığında karar bu fonksiyonda
DEĞİL `web_orch._run_thread()`'de veriliyor (decider yanıt VERMEZSE/format
hatası olursa `web_orch` bu fonksiyonu `has_decider=False` ile, Phase 1'le
BİREBİR AYNI şekilde çağırıp worker-consensus'a düşer) — bu fonksiyonun
kendisi bu yüzden DOKUNULMADI.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Worker'a enjekte edilen prompt'un SABİT kuyruğu — plan'daki sözleşmenin
# ta kendisi. Bilerek yerelleştirilmedi (TR/EN): bu bir protokol/parse
# sözleşmesi, kullanıcıya gösterilen düz metin değil — `_v1_error`'ın
# İngilizce kalması gibi aynı ilke (bkz. commands/web.py).
VERDICT_MARKER = "COPS-VERDICT:"
END_MARKER = "COPS-END"
# Brief'in kendisi çok-satırlı serbest metin — worker/decider'ın tek-satırlık
# verdict sözleşmesiyle PARSE EDİLEMEZ, bu yüzden ayrı bir sonlandırıcı.
BRIEF_END_MARKER = "COPS-BRIEF-END"

_STRIP_PREFIXES = ("the ", "sonuç:", "sonuc:", "answer:", "cevap:", "verdict:")
_MAX_VERDICT_CHARS = 200


def verdict_contract() -> str:
    return (
        "Finish your reply with these two lines, exactly:\n"
        f"{VERDICT_MARKER} <your answer in one line, max {_MAX_VERDICT_CHARS} chars>\n"
        f"{END_MARKER}"
    )


def brief_contract() -> str:
    return f"Finish your reply with a line containing exactly: {BRIEF_END_MARKER}"


def build_worker_prompt(task: str, verdict_hint: str = "") -> str:
    hint = f"\n\nVerdict format hint: {verdict_hint.strip()}" if verdict_hint.strip() else ""
    return f"{task.strip()}{hint}\n\n{verdict_contract()}"


def build_brief_prompt(task: str) -> str:
    """Controller'a gönderilen prompt (Phase 2, briefing fazı) — worker'ların
    GÖRECEĞİ metni yazmasını ister, task'ı KENDİSİ çözmesini DEĞİL."""
    return (
        f"{task.strip()}\n\n"
        "You are the controller for a team task (the text above). Write a complete, clear brief "
        "for the workers who will actually do the task — add any context/clarification they would "
        "need, keep the original intent, resolve ambiguity if you can. Do not solve the task "
        "yourself, just write the brief they will receive verbatim.\n\n"
        f"{brief_contract()}"
    )


def parse_brief(reply_text: str) -> Optional[str]:
    """`BRIEF_END_MARKER`'dan ÖNCEKİ metni brief olarak al — marker yoksa
    (ya da öncesi boşsa) None (çağıran bunu timeout'la AYNI şekilde ele alıp
    ham task metnine düşer, `web_orch._run_thread` docstring'i)."""
    if not reply_text or BRIEF_END_MARKER not in reply_text:
        return None
    brief = reply_text.split(BRIEF_END_MARKER, 1)[0].strip()
    return brief or None


def format_worker_bundle(results: List["RunResult"]) -> str:
    """Decider'a gösterilecek worker-yanıtları listesi — başarısız olanlar
    (`status != "ok"`) ham metin yerine kısa durum etiketiyle görünür,
    decider'ı yanıltacak boş/kesik metin göndermez."""
    lines = []
    for r in results:
        if r.status == "ok":
            lines.append(f"- {r.name} ({r.cli}): {r.text.strip()}")
        else:
            lines.append(f"- {r.name} ({r.cli}): [{r.status}]")
    return "\n".join(lines)


def build_decider_prompt(task: str, verdict_hint: str, worker_bundle: str) -> str:
    """Decider'a gönderilen prompt (Phase 2, deciding fazı) — worker'ların
    AYNI verdict sözleşmesini (VERDICT_MARKER/END_MARKER) kullanır, bu
    yüzden `parse_verdict()`/`normalize_verdict()` decider yanıtını da
    hiç değişmeden parse edebiliyor (`web_orch._run_decider`)."""
    hint = f"\n\nVerdict format hint: {verdict_hint.strip()}" if verdict_hint.strip() else ""
    return (
        f"You are the decider for a team task. Task given to the workers:\n{task.strip()}{hint}\n\n"
        f"Worker answers:\n{worker_bundle}\n\n"
        f"Read them and decide the single best final answer.\n\n{verdict_contract()}"
    )


def build_handoff_message(task: str, outcome: "Outcome") -> str:
    """Run bitince controller'a enjekte edilen tek-yönlü bilgi mesajı — bir
    yanıt BEKLEMEZ (handover/compact'ın wrap-up enjeksiyonuyla AYNI ilke,
    `web_orch._run_thread` sadece `tmux_send_keys` ile gönderip devam eder)."""
    lines = [f"Team task finished. Task: {task.strip()}", f"Outcome: {outcome.method}"]
    if outcome.final:
        lines.append(f"Final answer: {outcome.final}")
    if outcome.note:
        lines.append(outcome.note)
    return "\n".join(lines)


_VERDICT_LINE_RE = re.compile(re.escape(VERDICT_MARKER) + r"\s*(.*)")


def parse_verdict(reply_text: str) -> Optional[str]:
    """Worker'ın TAM yanıt metninden ham verdict satırını çıkar — hem
    `VERDICT_MARKER` hem `END_MARKER` yoksa None (çağıran bunu "no_envelope"
    olarak kaydeder, oy SAYILMAZ). Birden fazla `COPS-VERDICT:` satırı varsa
    (ör. worker kendi açıklamasında marker'dan bahsetmiş) SONUNCUSU alınır —
    gerçek/son karar en altta olma ihtimali en yüksek olan."""
    if not reply_text or END_MARKER not in reply_text or VERDICT_MARKER not in reply_text:
        return None
    verdict = None
    for line in reply_text.splitlines():
        m = _VERDICT_LINE_RE.match(line.strip())
        if m:
            verdict = m.group(1).strip()
    return verdict[:_MAX_VERDICT_CHARS] if verdict is not None else None


def normalize_verdict(raw: str) -> str:
    """Consensus gruplama anahtarı — casefold + tırnak/noktalama temizliği +
    boşluk sıkıştırma + küçük sabit bir önek listesi. Semantik eşleştirme
    DEĞİL (embedding yok, model-çağrısı yok) — bilerek deterministik/
    bağımsız, decider'ın (Phase 2) yaptığı işin ucuza taklidi değil."""
    s = re.sub(r"\s+", " ", raw.strip().casefold())
    for p in _STRIP_PREFIXES:
        if s.startswith(p):
            s = s[len(p):].strip()
            break
    return s.strip(" \t\"'`.,;:")


@dataclass
class Participant:
    role: str  # "worker" | "controller" | "decider" (Phase 2 — hepsi bağlandı, web_orch._preflight ≤1 controller/≤1 decider zorunlu kılıyor)
    host: str
    name: str
    cli: str = ""


@dataclass
class RunResult:
    seq: int
    kind: str  # "worker_result" (Phase 1) — "brief"/"decision"/"final" Phase 2
    role: str
    host: str
    name: str
    cli: str
    created_at: float
    status: str  # "ok" | "timeout" | "send_failed" | "no_envelope" | "unreachable"
    verdict: str = ""
    verdict_key: str = ""
    text: str = ""
    elapsed: float = 0.0


@dataclass
class Outcome:
    method: str  # "decider" | "unanimous" | "majority" | "single_worker" | "no_consensus" | "none"
    # Kasıtlı olarak WINNER'IN `.verdict`'i (kısa/temiz) — `.text` (ham yanıt,
    # COPS-VERDICT/COPS-END satırları dahil) DEĞİL. Ham metin isteyen zaten
    # ilgili worker'ın kendi `RunResult.text`'ine (frontend'de "görüntüle"
    # detayına) erişebiliyor; `outcome.final` kullanıcıya/controller'a
    # handoff mesajında GÖSTERİLEN alan (2026-09-10, Phase 2 live-test'inde
    # `.text` kullanıldığı bulundu — protokol satırları kullanıcıya sızıyordu).
    final: str = ""
    by: Optional[dict] = None
    tally: List[dict] = field(default_factory=list)
    abstained: List[dict] = field(default_factory=list)
    note: str = ""


@dataclass
class Run:
    id: str
    created_at: float
    updated_at: float
    status: str  # "briefing" | "working" | "deciding" | "done" | "needs_human" | "failed" | "cancelled"
    lang: str
    task: str
    verdict_hint: str
    worker_timeout: float
    participants: List[Participant] = field(default_factory=list)
    results: List[RunResult] = field(default_factory=list)
    outcome: Optional[Outcome] = None
    error: Optional[str] = None
    # Phase 2 — controller'ın brief fazının SONUCU (worker'lara gönderilen
    # ETKİN task metni); controller yoksa/brief üretilemediyse "" (ham
    # `task` kullanılır, bu alan boş kalır — "" ≠ "brief denendi ama boş
    # döndü", ikisi de aynı ETKİYİ taşır, ayrım UI için önemli değil).
    brief: str = ""


def resolve_outcome(results: List[RunResult], has_decider: bool = False) -> Outcome:
    """Plan'ın karar mekanizması: `has_decider=False` (Phase 1'in TEK yolu —
    decider rolü henüz bağlanmadı) → normalize edilmiş verdict'e göre
    RESPONDER'LAR arasında KESİN çoğunluk. Responder = `status=="ok"` VE
    parse edilmiş bir verdict'i olan worker; timeout/send_failed/no_envelope
    hepsi ABSTENTION (asla sessizce düşürülmez, `abstained`'da kalır, payda
    onları SAYMAZ).

    `has_decider=True`: bu fonksiyon KARARI VERMEZ (decider'ın kendi verdict'i
    kazanır, o mantık Phase 2'nin `web_orch.py`'sinde olacak) — burada sadece
    documented bir no-op branch, plan'ın Phase-2 çağrı şeklini şimdiden
    karşılayan bir imza-uyumluluğu için."""
    if has_decider:
        abstained = [{"name": r.name, "status": r.status} for r in results if r.status != "ok"]
        return Outcome(method="decider", note="decider path not implemented in Phase 1", abstained=abstained)

    responders = [r for r in results if r.status == "ok" and r.verdict_key]
    responder_names = {r.name for r in responders}
    abstained = [{"name": r.name, "status": r.status} for r in results if r.name not in responder_names]

    if not responders:
        return Outcome(method="none", abstained=abstained, note="no worker produced a parseable verdict")

    if len(responders) == 1:
        r = responders[0]
        return Outcome(
            method="single_worker", final=r.verdict, by={"host": r.host, "name": r.name, "cli": r.cli},
            tally=[{"verdict_key": r.verdict_key, "votes": 1, "voters": [r.name]}], abstained=abstained,
            note="only one worker responded",
        )

    groups: Dict[str, List[RunResult]] = {}
    for r in responders:
        groups.setdefault(r.verdict_key, []).append(r)
    tally = [{"verdict_key": k, "votes": len(v), "voters": [x.name for x in v]} for k, v in groups.items()]
    tally.sort(key=lambda t: -t["votes"])

    top_key = tally[0]["verdict_key"]
    top_group = groups[top_key]
    if len(top_group) * 2 > len(responders):  # KESİN çoğunluk (yarıdan fazla)
        method = "unanimous" if len(top_group) == len(responders) else "majority"
        winner = top_group[0]
        abst_note = f", {len(abstained)} abstained" if abstained else ""
        return Outcome(
            method=method, final=winner.verdict, tally=tally, abstained=abstained,
            note=f"{len(top_group)}/{len(responders)} worker aynı verdiği verdi{abst_note}",
        )

    return Outcome(
        method="no_consensus", tally=tally, abstained=abstained,
        note="no verdict group reached a majority among responders",
    )
