"""files — web panelinin dosya-gezgini/indirme özelliği: bir session'ın izin
verilen kök dizinleri içindeki dosyaları listele/indir.

2026-09-05, kullanıcı: "...folderları browse ve dosya indirme ve dosyaları
terminalde listeleme ve indirme ... şimdilik en buyuk eksikliğim bu" —
TODO.md'nin "folder browser" maddesinin implementasyonu. Kapsam kullanıcı
tarafından netleştirildi: SADECE session'ın proje klasörü (cwd) + varsa
provider'ın kendi per-proje meta-dizini (bkz. `CliProvider.extra_file_roots()`)
— makinedeki HERHANGİ bir yol DEĞİL. `/tmp` (scratchpad) kasıtlı olarak dahil
EDİLMEDİ (TODO.md'de "kullanıcı onayı bekleniyor" olarak not düşülmüştü,
netleşmeden eklenmedi — istenirse ayrı bir turda eklenebilir).

Path-traversal/arbitrary-file-read'e karşı TEK kapı noktası:
`_resolve_within_roots` (realpath + prefix kontrolü, symlink'ler dahil) — her
`list_dir`/`resolve_download` çağrısında zorunlu, caller'ın kendisi
atlayamaz/unutamaz (fonksiyonların KENDİSİ doğruluyor)."""
from __future__ import annotations
import os
from typing import List, Optional, Tuple

from .providers import get_provider
from .session import Session

MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024  # kişisel/tek-kullanıcı araç ama kazara dev bir dosyayı tam belleğe yüklemeden önce reddet — `_serve_static` gibi read_bytes() kullanıyoruz, streaming yok
MAX_VIEW_BYTES = 5 * 1024 * 1024  # inline "görüntüle" indirmeden çok daha küçük bir sınır olmalı — md/txt/html kaynak dosyaları, büyük veri dökümü değil


def roots_for_session(s: Session) -> List[Tuple[str, str]]:
    """(key, absolute-path) listesi — bu session için izin verilen kök
    dizinler. Her zaman en az "project" (cwd, hâlâ diskte varsa); provider
    kendi ekstra kök(ler)ini `extra_file_roots()` ile ekleyebilir (şu an
    sadece claude — kendi transcript meta-dizini)."""
    out: List[Tuple[str, str]] = []
    cwd = os.path.normpath(os.path.abspath(s.cwd))
    if os.path.isdir(cwd):
        out.append(("project", cwd))
    provider = get_provider(s.cli)
    for key, root in provider.extra_file_roots(s.cwd):
        if os.path.isdir(root):
            out.append((key, root))
    return out


def _resolve_within_roots(path: str, roots: List[Tuple[str, str]]) -> Optional[str]:
    """`path`'in GERÇEKTEN (symlink çözülmüş) izin verilen köklerden birinin
    altında (ya da tam kendisi) olduğunu doğrular. Uymuyorsa None — caller
    403/404 kararını kendi verir."""
    try:
        real = os.path.realpath(path)
    except OSError:
        return None
    for _key, root in roots:
        real_root = os.path.realpath(root)
        if real == real_root or real.startswith(real_root + os.sep):
            return real
    return None


def list_dir(s: Session, path: Optional[str]) -> dict:
    """`path` verilmezse session'ın İLK kökü (proje cwd'si) listelenir.
    Hata kodları ("no_roots"/"forbidden"/"not_found") `web.py`'de
    `files_<kod>` ERR anahtarına eşlenir."""
    roots = roots_for_session(s)
    if not roots:
        return {"ok": False, "error": "no_roots"}
    target = path or roots[0][1]
    real = _resolve_within_roots(target, roots)
    if real is None:
        return {"ok": False, "error": "forbidden"}
    if not os.path.isdir(real):
        return {"ok": False, "error": "not_found"}
    entries: List[dict] = []
    try:
        with os.scandir(real) as it:
            for entry in it:
                try:
                    is_dir = entry.is_dir(follow_symlinks=True)
                    st = entry.stat(follow_symlinks=True)
                except OSError:
                    continue  # kırık symlink/izin sorunu — sessizce atla, listenin geri kalanını bozma
                entries.append({"name": entry.name, "is_dir": is_dir,
                                 "size": st.st_size, "mtime": st.st_mtime})
    except OSError:
        return {"ok": False, "error": "not_found"}
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    return {"ok": True, "roots": [{"key": k, "path": p} for k, p in roots],
            "path": real, "entries": entries}


def _resolve_file(s: Session, path: str, max_bytes: int) -> Tuple[Optional[str], Optional[str]]:
    """`resolve_download`/`read_text`'in PAYLAŞTIĞI adım: kök-içi mi + gerçekten
    bir dosya mı + boyut sınırı içinde mi. (gerçek-yol, None) başarılı;
    (None, hata-kodu) başarısız — kodlar forbidden/not_found/too_large,
    `web.py`'de `files_<kod>` ERR anahtarına eşlenir."""
    roots = roots_for_session(s)
    real = _resolve_within_roots(path, roots)
    if real is None:
        return None, "forbidden"
    if not os.path.isfile(real):
        return None, "not_found"
    try:
        size = os.path.getsize(real)
    except OSError:
        return None, "not_found"
    if size > max_bytes:
        return None, "too_large"
    return real, None


def resolve_download(s: Session, path: str) -> Tuple[Optional[str], Optional[str]]:
    """(gerçek-yol, None) başarılı; (None, hata-kodu) başarısız."""
    return _resolve_file(s, path, MAX_DOWNLOAD_BYTES)


def read_text(s: Session, path: str) -> Tuple[Optional[str], Optional[str]]:
    """İnline "görüntüle" için: (metin, None) başarılı; (None, hata-kodu)
    başarısız. `MAX_VIEW_BYTES` (indirmeden çok daha küçük) sınırını kullanır.
    Binary bir dosya yanlışlıkla istenirse `errors="replace"` sayesinde
    ÇÖKMEZ (okunabilir olmayan baytlar U+FFFD olur) — frontend hangi
    uzantılar için "görüntüle" göstereceğine kendi karar verir, burası
    savunmacı bir son kapı."""
    real, err = _resolve_file(s, path, MAX_VIEW_BYTES)
    if err:
        return None, err
    try:
        with open(real, encoding="utf-8", errors="replace") as f:
            return f.read(), None
    except OSError:
        return None, "not_found"


def validate_candidates(s: Session, candidates: List[str]) -> List[str]:
    """Terminal çıktısında regex'le yakalanan dosya-yolu ADAYLARINDAN
    GERÇEKTEN var olan + izin verilen dosyalara karşılık gelenleri (sırayı
    koruyarak, dedup'lanmış) döndürür — regex kendi başına güvenilir değil
    (2026-09-05, TODO.md'nin kendi notu: "salt regex güvenilir olmayabilir"),
    bu fonksiyon o filtrenin KENDİSİ. Dizinler/uzak-kök-dışı/var-olmayan
    yollar sessizce elenir, hata döndürmez (caller için 'aday listesi' — bir
    tanesinin geçersiz olması diğerlerini etkilemez)."""
    roots = roots_for_session(s)
    if not roots:
        return []
    seen = set()
    out: List[str] = []
    for c in candidates:
        real = _resolve_within_roots(c, roots)
        if real and real not in seen and os.path.isfile(real):
            seen.add(real)
            out.append(real)
    return out
