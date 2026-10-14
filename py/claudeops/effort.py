"""Effort (düşünme seviyesi) yardımcıları: sağlayıcıdan bağımsız, saf fonksiyonlar.

Neden var (2026-10-14, kullanıcı: "effort'ları toplayıp modele göre ayarlayamaz mıyız?
bizde liste olsun, modellere/CLI'lara göre hangisi olursa onu gönderelim; yoksa uygununu
set edelim"): panelin sunduğu effort listesi HER modelde geçerli değil.
- agy seviyeyi model kimliğinin İÇİNE gömüyor (`gemini-3.8-flash-high`) ve kimlikle
  ÇATIŞAN bir `--effort` (panelin varsayılanı `max`) modeli SESSİZCE agy'nin kendi
  varsayılanına düşürüyor (TODO.md 2026-10-09).
- codex model başına desteklenen listeyi kendi `models_cache.json`'ında tutuyor.

Burada yalnız model-bağımsız mantık var: seviye merdiveni, kimlikten kademe okuma,
"en yakın uygun seviye" seçimi. Hangi modelin hangi seviyeleri desteklediği bilgisi
sağlayıcıda (`CliProvider.model_effort_levels`), çünkü kaynağı CLI'a göre değişiyor.
"""
from __future__ import annotations
from typing import Iterable, List, Optional, Tuple

# Düşükten yükseğe; claude/agy/codex/copilot'un bilinen seviye adlarının birleşimi.
EFFORT_LADDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
_RANK = {name: i for i, name in enumerate(EFFORT_LADDER)}

# Model kimliğinin SONUNA gömülen kademe adları (`gemini-3.8-flash-high`, `...-medium`).
# Bilerek dar tutuldu: `none`/`ultra` yok, yoksa `gemini-ultra` gibi bir ürün adının
# sonu kademe sanılırdı.
_ID_TIERS = frozenset({"minimal", "low", "medium", "high", "xhigh", "max"})


def effort_rank(level: Optional[str]) -> Optional[int]:
    """Merdivendeki sırası (büyük = daha çok düşünür); tanınmayan ad için None."""
    return _RANK.get(level) if isinstance(level, str) else None


def split_tier(model_id: Optional[str]) -> Tuple[str, Optional[str]]:
    """`(taban, kademe)`: `gemini-3.8-flash-high` -> (`gemini-3.8-flash`, `high`).
    Kimlik bir kademeyle BİTMİYORSA (`claude-sonnet-5-5`, `claude-opus-4-6-thinking`)
    kademe None ve taban kimliğin kendisi."""
    if not isinstance(model_id, str):
        return ("", None)
    head, sep, tail = model_id.rpartition("-")
    if sep and head and tail in _ID_TIERS:
        return (head, tail)
    return (model_id, None)


def sort_levels(levels: Iterable[str]) -> List[str]:
    """Merdivene göre düşükten yükseğe, tekrarsız. Merdivende olmayan (bilinmeyen)
    adlar atılmaz, girdi sırasıyla sona eklenir."""
    seen: List[str] = []
    for lv in levels:
        if isinstance(lv, str) and lv and lv not in seen:
            seen.append(lv)
    known = sorted((lv for lv in seen if lv in _RANK), key=_RANK.__getitem__)
    return known + [lv for lv in seen if lv not in _RANK]


def nearest_effort(requested: Optional[str], levels: List[str], default: str = "medium") -> Optional[str]:
    """`levels` (modelin desteklediği seviyeler) içinden `requested`'e uygun olanı seç.

    - `requested` listedeyse AYNEN döner (hiçbir şey yeniden yazılmaz).
    - Değilse, ondan AŞAĞIDAKİ en yakın seviye (maliyeti istenenden fazla artırmamak
      için, handover'daki "effort asla yükselmez" ilkesiyle aynı); aşağıda hiç yoksa
      yukarıdakilerin en düşüğü.
    - `requested` boş/tanınmayan ise `default` ölçü alınır (listedeyse o).
    - `levels` boşsa None."""
    if not levels:
        return None
    if requested in levels:
        return requested
    ranked = [(effort_rank(lv), lv) for lv in levels if effort_rank(lv) is not None]
    if not ranked:  # hepsi bilinmeyen ad: sıralayamayız, ilkini ver
        return levels[0]
    wanted = effort_rank(requested)
    if wanted is None:  # boş/tanınmayan istek: `default` ölçü alınır (listedeyse zaten o seçilir)
        wanted = effort_rank(default)
        if wanted is None:
            return min(ranked)[1]
    at_or_below = [(r, lv) for r, lv in ranked if r <= wanted]
    if at_or_below:
        return max(at_or_below)[1]
    return min(ranked)[1]
