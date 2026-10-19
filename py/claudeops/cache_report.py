"""Prompt-cache raporu: transkriptlerden "soğuk uyanış" israfı (TBD#87 öneri A, ölçüm kısmı).

claude'un istem önbelleği 1 saatlik ve bir UÇURUM (`providers/claude_provider.py::PROMPT_CACHE_TTL_SECONDS`): bir
oturumda iki gerçek model isteği arası TTL'i geçerse sonraki istek bağlamın tamamını yeniden yazar (`usage.
cache_creation_input_tokens`), geçmezse okur (`cache_read_input_tokens`, çok daha ucuz). Bu modül `~/.claude/projects`
altındaki transkriptleri okuyup bunun filoda ne kadar olduğunu SAYAR: kaç soğuk uyanış, yeniden yazılan token, hangi
aralıkta, hangi modelde, hangi oturumda. Yalnız ölçüm: hiçbir oturuma dokunmaz, hiçbir şey göndermez, fiyat varsaymaz
(yeniden yazılan token x modelin 1 saatlik yazma - okuma fiyatı kullanıcıda; AE `agent_economy` TBD madde 15'teki
"canlı tutma" başa baş hesabı bu dağılımı kullanır).

Kurallar: yalnız ana zincir sayılır (`isSidechain` alt-ajan satırları ayrı bir bağlam), `<synthetic>`/kullanımsız
satırlar sayılmaz (`claude_provider._real_request_epoch` ile AYNI süzgeç), aynı `requestId`yi taşıyan ardışık satırlar
(bir yanıtın düşünme/metin/araç blokları ayrı satır olarak yazılıyor, usage aynı) TEK istek sayılır. Bir dosyanın İLK
isteği sayılmaz (önceki istek yok; resume ile açılmış bir dosyanın eski dosyadaki geçmişi görülmez, bu yüzden resume
sonrası ilk isteğin soğuk uyanışı buraya yansımaz).
"""
from __future__ import annotations

import json
import os
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from .providers.claude_provider import PROJECTS_DIR, PROMPT_CACHE_TTL_SECONDS, _real_request_epoch

_ASSISTANT = b'"type":"assistant"'
_TITLE = b'"type":"custom-title"'

# Boşluk kovaları: (üst sınır sn, etiket). Son kova sonsuz. 55-60 dk "kıl payı" (uyarı payı 5 dk) ayrı görünsün.
GAP_BUCKETS: List[Tuple[Optional[int], str]] = [
    (300, "< 5 dk"), (1800, "5-30 dk"), (3300, "30-55 dk"), (3600, "55-60 dk (kıl payı)"),
    (7200, "1-2 sa (SOĞUK)"), (43200, "2-12 sa (SOĞUK)"), (172800, "12-48 sa (SOĞUK)"), (None, "> 48 sa (SOĞUK)"),
]


@dataclass
class Req:
    t: float
    model: str
    fresh: int      # usage.input_tokens (önbelleğe hiç girmeyen)
    write: int      # usage.cache_creation_input_tokens
    read: int       # usage.cache_read_input_tokens


@dataclass
class Transcript:
    path: str
    name: str
    reqs: List[Req] = field(default_factory=list)


@dataclass
class Tally:
    requests: int = 0
    cold: int = 0
    cold_write: int = 0       # soğuk uyanışlarda yeniden yazılan token
    switch: int = 0           # sıcakken model değişimi (önbellek modele özgü: zaman değil, geçiş yeniden yazdırdı)
    switch_write: int = 0
    warm_write: int = 0       # geri kalan yazma (yeni içerik)
    read: int = 0
    gaps_cold: List[float] = field(default_factory=list)


def _usage_int(usage: dict, key: str) -> int:
    v = usage.get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


def read_transcript(path: Path) -> Transcript:
    """Dosyadaki ana zincir gerçek isteklerini (dosya sırasıyla) ve oturum adını (son `custom-title`) okur. Bozuk
    satır atlanır, dosya okunamazsa boş döner. Yalnız ilgili satırlar JSON'a çevrilir (dosyalar onlarca MB, çoğu
    satır dev API-istek kopyaları)."""
    tr = Transcript(path=str(path), name=path.stem[:8])
    last_key: Optional[Tuple] = None
    try:
        with open(path, "rb") as f:
            for line in f:
                if _TITLE in line:
                    try:
                        title = json.loads(line).get("customTitle")
                    except ValueError:
                        continue
                    if isinstance(title, str) and title:
                        tr.name = title
                    continue
                if _ASSISTANT not in line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if obj.get("type") != "assistant":
                    continue
                epoch = _real_request_epoch(obj)       # sidechain / <synthetic> / kullanımsız satırları eler
                if epoch is None:
                    continue
                msg = obj["message"]
                usage = msg["usage"]
                req = Req(epoch, str(msg.get("model")), _usage_int(usage, "input_tokens"),
                          _usage_int(usage, "cache_creation_input_tokens"), _usage_int(usage, "cache_read_input_tokens"))
                key = (obj.get("requestId") or None, req.model, req.fresh, req.write, req.read)
                if key == last_key:                    # aynı yanıtın sonraki bloğu
                    continue
                last_key = key
                tr.reqs.append(req)
    except OSError:
        pass
    return tr


def scan(root: str = PROJECTS_DIR, days: float = 7.0, now: Optional[float] = None,
         project: str = "", exclude_remote: bool = False) -> Iterator[Transcript]:
    """`root/*/*.jsonl` içinden son `days` günde değişmiş olanları okur. `project`: dizin adında geçen alt dize.
    `exclude_remote`: uzak host'tan içe aktarılan transkriptleri (dizin adı `-home-<kullanıcı>-remote-` ile başlar) atla."""
    cutoff = (time.time() if now is None else now) - days * 86400
    base = Path(root)
    if not base.is_dir():
        return
    for d in sorted(base.iterdir()):
        if not d.is_dir() or (project and project not in d.name):
            continue
        if exclude_remote and "-remote-" in d.name:
            continue
        for p in sorted(d.glob("*.jsonl")):
            try:
                if p.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            tr = read_transcript(p)
            if len(tr.reqs) > 1:
                yield tr


def bucket_label(gap: float) -> str:
    for upper, label in GAP_BUCKETS:
        if upper is None or gap < upper:
            return label
    return GAP_BUCKETS[-1][1]


@dataclass
class Report:
    ttl: int
    transcripts: int = 0
    total: Tally = field(default_factory=Tally)
    by_model: Dict[str, Tally] = field(default_factory=lambda: defaultdict(Tally))
    by_gap: Dict[str, List[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0, 0]))  # istek, yazma, okuma
    by_session: Dict[str, Tally] = field(default_factory=lambda: defaultdict(Tally))


def analyze(transcripts, ttl: int = PROMPT_CACHE_TTL_SECONDS) -> Report:
    """Her dosyada ardışık istek çiftlerini sınıflar: boşluk >= ttl = SOĞUK UYANIŞ (yazma = yeniden yazılan bağlam);
    boşluk < ttl ama model değişti = geçiş yeniden yazdırdı (önbellek modele özgü); aksi sıcak. İlk istek sayılmaz."""
    rep = Report(ttl=ttl)
    for tr in transcripts:
        rep.transcripts += 1
        ordered = sorted(tr.reqs, key=lambda r: r.t)
        for prev, cur in zip(ordered, ordered[1:]):
            gap = max(0.0, cur.t - prev.t)
            cold = gap >= ttl
            switched = (not cold) and cur.model != prev.model
            for tally in (rep.total, rep.by_model[cur.model], rep.by_session[f"{tr.name}\t{tr.path}"]):
                tally.requests += 1
                tally.read += cur.read
                if cold:
                    tally.cold += 1
                    tally.cold_write += cur.write
                    tally.gaps_cold.append(gap)
                elif switched:
                    tally.switch += 1
                    tally.switch_write += cur.write
                else:
                    tally.warm_write += cur.write
            row = rep.by_gap[bucket_label(gap)]
            row[0] += 1
            row[1] += cur.write
            row[2] += cur.read
    return rep


def human(n: float) -> str:
    n = float(n)
    for unit, size in (("G", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(n) >= size:
            return f"{n / size:.1f}{unit}".replace(".0", "")
    return str(int(n))


def hours(sec: float) -> str:
    return f"{sec / 3600:.1f} sa" if sec >= 3600 else f"{sec / 60:.0f} dk"


def render(rep: Report, days: float, top: int = 10) -> str:
    out: List[str] = []
    t = rep.total
    out.append(f"Prompt cache raporu: son {days:g} gün, {rep.transcripts} transkript, {t.requests} ana-zincir isteği "
               f"(alt-ajan satırları ve her dosyanın ilk isteği sayılmaz).")
    out.append(f"TTL {rep.ttl} sn. SOĞUK UYANIŞ = aynı transkriptte bir önceki gerçek istekten bu yana >= TTL geçmiş istek; "
               f"yazılan token o anda yeniden yazılan bağlamdır.")
    if not t.requests:
        out.append("(hiç istek çifti bulunamadı)")
        return "\n".join(out)
    total_write = t.cold_write + t.switch_write + t.warm_write
    share = 100.0 * t.cold_write / total_write if total_write else 0.0
    out.append("")
    out.append(f"{'':<22}{'istek':>8}{'soğuk':>7}{'soğukta yazılan':>17}{'geçişte yazılan':>17}{'okunan':>10}")
    for label, tally in [("TÜM MODELLER", t)] + sorted(rep.by_model.items(), key=lambda kv: -kv[1].cold_write):
        out.append(f"{label[:21]:<22}{tally.requests:>8}{tally.cold:>7}{human(tally.cold_write):>17}"
                   f"{human(tally.switch_write):>17}{human(tally.read):>10}")
    out.append(f"Soğuk uyanışlar yazılan tokenin %{share:.0f}'ini oluşturuyor (toplam yazma {human(total_write)}).")
    out.append("")
    out.append(f"{'boşluk (önceki istekten)':<26}{'istek':>8}{'yazılan':>10}{'okunan':>10}")
    for _, label in GAP_BUCKETS:
        n, w, r = rep.by_gap.get(label, [0, 0, 0])
        if n:
            out.append(f"{label:<26}{n:>8}{human(w):>10}{human(r):>10}")
    if t.gaps_cold:
        out.append(f"Soğuk uyanış boşluğu: ortanca {hours(statistics.median(t.gaps_cold))}, "
                   f"en uzun {hours(max(t.gaps_cold))}.")
    ranked = sorted(((k, v) for k, v in rep.by_session.items() if v.cold), key=lambda kv: -kv[1].cold_write)[:top]
    if ranked:
        out.append("")
        out.append(f"Soğukta en çok yazan oturumlar (ilk {len(ranked)}):")
        out.append(f"{'oturum':<28}{'soğuk':>7}{'yazılan':>10}{'ortanca boşluk':>16}")
        for key, tally in ranked:
            name = key.split("\t", 1)[0]
            out.append(f"{name[:27]:<28}{tally.cold:>7}{human(tally.cold_write):>10}"
                       f"{hours(statistics.median(tally.gaps_cold)):>16}")
    return "\n".join(out)
