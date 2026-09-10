"""TOBEDECIDED#15 — controller/worker/decider orchestration, pure core.

Sadece dataclass'lar + `resolve_outcome()` + prompt-üretimi — hiç tmux/HTTP/
thread yok, bu yüzden sıfır canlı CLI'yla unit-test edilebilir. Asıl
dispatch/wait/persist motoru `commands/web_orch.py`'de.

Phase 1 kapsamı: SADECE worker rolü (controller/decider henüz bağlanmadı —
Phase 2). Bu yüzden `build_decider_prompt`/`build_brief_prompt`/
`build_handoff_message` (plan'da adı geçen, controller/decider'a özel prompt
üreticileri) BİLEREK burada YOK — ihtiyaç controller/decider rolleri
bağlanınca ortaya çıkacak, şimdiden spekülatif yazılmadı.
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

_STRIP_PREFIXES = ("the ", "sonuç:", "sonuc:", "answer:", "cevap:", "verdict:")
_MAX_VERDICT_CHARS = 200


def verdict_contract() -> str:
    return (
        "Finish your reply with these two lines, exactly:\n"
        f"{VERDICT_MARKER} <your answer in one line, max {_MAX_VERDICT_CHARS} chars>\n"
        f"{END_MARKER}"
    )


def build_worker_prompt(task: str, verdict_hint: str = "") -> str:
    hint = f"\n\nVerdict format hint: {verdict_hint.strip()}" if verdict_hint.strip() else ""
    return f"{task.strip()}{hint}\n\n{verdict_contract()}"


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
    role: str  # "worker" (Phase 1) — "controller"/"decider" değerleri kabul edilir ama web_orch._preflight henüz reddediyor
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
    status: str  # "working" | "done" | "needs_human" | "failed" | "cancelled"
    lang: str
    task: str
    verdict_hint: str
    worker_timeout: float
    participants: List[Participant] = field(default_factory=list)
    results: List[RunResult] = field(default_factory=list)
    outcome: Optional[Outcome] = None
    error: Optional[str] = None


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
            method="single_worker", final=r.text, by={"host": r.host, "name": r.name, "cli": r.cli},
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
            method=method, final=winner.text, tally=tally, abstained=abstained,
            note=f"{len(top_group)}/{len(responders)} worker aynı verdiği verdi{abst_note}",
        )

    return Outcome(
        method="no_consensus", tally=tally, abstained=abstained,
        note="no verdict group reached a majority among responders",
    )
