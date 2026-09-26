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
import shutil
from typing import List, Optional, Tuple

from .providers import get_provider
from .session import Session

MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024  # kişisel/tek-kullanıcı araç ama kazara dev bir dosyayı tam belleğe yüklemeden önce reddet — `_serve_static` gibi read_bytes() kullanıyoruz, streaming yok
MAX_VIEW_BYTES = 5 * 1024 * 1024  # inline "görüntüle" indirmeden çok daha küçük bir sınır olmalı — md/txt/html kaynak dosyaları, büyük veri dökümü değil
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # MAX_DOWNLOAD_BYTES ile simetrik — yükleme TARAFI (web.py'nin _handle_files_upload'ı) chunk'lar halinde diske yazıyor, streaming var; sınır yine de kazara dev bir dosyayı reddetmek için


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


def resolve_upload_target(s: Session, dir_path: Optional[str], filename: str,
                           overwrite: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """`list_dir`'in YAZMA kardeşi — yükleme hedefini çözer. `dir_path`
    (verilmezse ilk kök) önce `_resolve_within_roots`'tan geçer (aynı tek
    kapı), SONRA `filename` `os.path.basename()`'le soyulur — `/`/`..`
    hiçbir şekilde hayatta kalamaz, bu yüzden birleşik hedefin AYRICA kök-içi
    doğrulamaya ihtiyacı yok (real_dir zaten kök-içi, safe_name'in kendisi
    dizin değiştiremez). (gerçek-yol, None) başarılı; (None, hata-kodu)
    başarısız — kodlar no_roots/forbidden/not_found (hedef dizin yok)/
    bad_filename/exists (overwrite=False iken zaten var)."""
    roots = roots_for_session(s)
    if not roots:
        return None, "no_roots"
    target_dir = dir_path or roots[0][1]
    real_dir = _resolve_within_roots(target_dir, roots)
    if real_dir is None:
        return None, "forbidden"
    if not os.path.isdir(real_dir):
        return None, "not_found"
    safe_name = os.path.basename((filename or "").strip())
    if not safe_name or safe_name in (".", ".."):
        return None, "bad_filename"
    dest = os.path.join(real_dir, safe_name)
    if not overwrite and os.path.exists(dest):
        return None, "exists"
    return dest, None


def _is_a_root(real: str, roots: List[Tuple[str, str]]) -> bool:
    """Silme/yeniden-adlandırma bir KÖKÜN KENDİSİNİ hedef alıyor mu? — bu
    ikisi (upload/mkdir'in aksine) kökün İÇİNDEKİ bir şeyi değil, kökün
    kendisini de hedef alabilir (`path` bir root'un tam kendisiyse), o
    durumda izin verilmez: `roots_for_session()`'ın ürettiği "project"/
    "claude-transcripts" gibi bir kök silinir/adı değişirse o session'ın
    dosya gezicisi kalıcı olarak kırılır."""
    return any(real == os.path.realpath(r) for _key, r in roots)


def delete_path(s: Session, path: str) -> dict:
    """Dosya YA DA dizin sil (dizin ise `resolve_download`/`_resolve_file`'ın
    aksine İÇERİĞE/boyuta bakmadan, `shutil.rmtree` ile içindekilerle
    birlikte — bir upload/mkdir'le oluşturulmuş bir klasörü geri almanın
    doğal yolu). Geri dönüşü YOK (çöp kutusu/trash yok, kişisel/tek-kullanıcı
    araç) — çağıran taraf (web.py) onayı ZATEN almış olmalı."""
    roots = roots_for_session(s)
    real = _resolve_within_roots(path, roots)
    if real is None:
        return {"ok": False, "error": "forbidden"}
    if _is_a_root(real, roots):
        return {"ok": False, "error": "is_root"}
    if not os.path.exists(real):
        return {"ok": False, "error": "not_found"}
    try:
        if os.path.isdir(real) and not os.path.islink(real):
            shutil.rmtree(real)
        else:
            os.remove(real)
    except OSError as e:
        return {"ok": False, "error": "io_error", "detail": str(e)}
    return {"ok": True}


def rename_path(s: Session, path: str, new_name: str) -> dict:
    """Aynı dizin İÇİNDE yeniden adlandırma — bir `mv` (dizinler-arası
    taşıma) DEĞİL, `new_name` yine `os.path.basename()`'le soyulur (upload'un
    `filename`'iyle AYNI disiplin). Hedef zaten aynı isimse no-op başarı
    (hata değil — kullanıcı ismi hiç değiştirmeden 'kaydet'e basmış gibi)."""
    roots = roots_for_session(s)
    real = _resolve_within_roots(path, roots)
    if real is None:
        return {"ok": False, "error": "forbidden"}
    if _is_a_root(real, roots):
        return {"ok": False, "error": "is_root"}
    if not os.path.exists(real):
        return {"ok": False, "error": "not_found"}
    safe_name = os.path.basename((new_name or "").strip())
    if not safe_name or safe_name in (".", ".."):
        return {"ok": False, "error": "bad_filename"}
    new_real = os.path.join(os.path.dirname(real), safe_name)
    if new_real == real:
        return {"ok": True, "path": real}
    if os.path.exists(new_real):
        return {"ok": False, "error": "exists"}
    try:
        os.rename(real, new_real)
    except OSError as e:
        return {"ok": False, "error": "io_error", "detail": str(e)}
    return {"ok": True, "path": new_real}


def make_folder(s: Session, dir_path: Optional[str], folder_name: str) -> dict:
    """`resolve_upload_target`'ın AYNI deseni ama dosya değil dizin
    oluşturuyor — TEK seviye (`os.mkdir`, `os.makedirs` DEĞİL: "burada bir
    klasör" niyeti, ara dizinleri kendiliğinden icat eden derin bir yol
    değil)."""
    roots = roots_for_session(s)
    if not roots:
        return {"ok": False, "error": "no_roots"}
    target_dir = dir_path or roots[0][1]
    real_dir = _resolve_within_roots(target_dir, roots)
    if real_dir is None:
        return {"ok": False, "error": "forbidden"}
    if not os.path.isdir(real_dir):
        return {"ok": False, "error": "not_found"}
    safe_name = os.path.basename((folder_name or "").strip())
    if not safe_name or safe_name in (".", ".."):
        return {"ok": False, "error": "bad_filename"}
    dest = os.path.join(real_dir, safe_name)
    if os.path.exists(dest):
        return {"ok": False, "error": "exists"}
    try:
        os.mkdir(dest)
    except OSError as e:
        return {"ok": False, "error": "io_error", "detail": str(e)}
    return {"ok": True, "path": dest}


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


def resolve_path(s: Session, path: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """`path` verilmezse session'ın İLK kökü (proje cwd'si) kullanılır — ör.
    "VS Code'da aç": tek bir dosya adı verilmemişse tüm projeyi aç. `resolve_
    download`/`read_text`'ten farkı: dosya YA DA dizin olabilir, boyut sınırı
    yok (içerik OKUNMUYOR, sadece var olan bir yola işaret etmesi yeterli).
    (gerçek-yol, None) başarılı; (None, hata-kodu) başarısız."""
    roots = roots_for_session(s)
    if not roots:
        return None, "no_roots"
    target = path or roots[0][1]
    real = _resolve_within_roots(target, roots)
    if real is None:
        return None, "forbidden"
    if not os.path.exists(real):
        return None, "not_found"
    return real, None


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
