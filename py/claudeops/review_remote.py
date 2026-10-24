"""Uzak projede review: yerel kopya (TBD#114). SAF yardımcılar + tek `git` çağrısı; steward/web_review'a bağımlılık YOK.

Sahip kararı proje başına `Project.review_where`: "" / "ask" (henüz sorulmadı / cevap bekliyor), "local" (yerel kopya,
`Project.local_path`), "remote" (uzakta koş: v1'de KOŞMAZ, yalnız kayıt), "off" (bu projede hiç sorma, review yok).
Yerel kopyaya YAZMA yok: review öncesi `git pull --ff-only`; kopya kirliyse ya da ileri sarılamıyorsa DUR."""
import os
import re
import subprocess
from typing import Callable, List, Optional, Tuple

WHERE_VALUES = ("", "ask", "local", "remote", "off")
ASK_SOURCE = "reviewer-where"          # soruyu reviewer açtı; cevap `steward.answer_question` kancasında işlenir
OPT_LOCAL, OPT_REMOTE, OPT_OFF = "Yerel kopya", "Uzak", "Vazgeç"
OPTIONS = [OPT_LOCAL, OPT_REMOTE, OPT_OFF]
GIT_TIMEOUT_SECONDS = 120

# Yerel kopyanın aranacağı yerler (proje adının altında): sahip düzeni `~/work/projects/tmp/<ad>` ve `~/work/projects/<ad>`.
DEFAULT_ROOTS = ("~/work/projects/tmp", "~/work/projects")


def ask_text(project: str, host: str, lang: str = "tr") -> str:
    if lang == "en":
        return (f"Project {project} runs on remote host {host}. Where should the reviewer work on it: a LOCAL COPY "
                f"(git pull --ff-only before each review, never writes to the remote), REMOTE (not available yet; "
                f"recorded only) or skip it (no review)? You can also reply with the local clone's absolute path.")
    return (f"{project} projesi {host} uzak host'unda. Reviewer üzerinde nerede çalışsın: YEREL KOPYA (her review "
            f"öncesi git pull --ff-only, uzağa yazılmaz), UZAK (henüz çalışmaz; yalnız kaydedilir) ya da vazgeç "
            f"(review yok)? Yerel kopyanın mutlak yolunu da yazabilirsin.")


def is_git_dir(path: str) -> bool:
    return bool(path) and os.path.isdir(path) and os.path.exists(os.path.join(path, ".git"))


def find_local_copy(name: str, roots: Tuple[str, ...] = DEFAULT_ROOTS) -> str:
    """`<kök>/<ad>` biçiminde, git deposu olan ilk dizin; yoksa ""."""
    for root in roots:
        cand = os.path.join(os.path.expanduser(root), name)
        if is_git_dir(cand):
            return cand
    return ""


_PATH_RE = re.compile(r"(?:^|\s)((?:/|~/)[^\s`'\"]+)")


def parse_answer(answer: str) -> Tuple[str, str]:
    """Cevap -> (review_where, yol). Seçenek metni ya da serbest metin: "yerel"/"local" -> local, "uzak"/"remote" ->
    remote, "vazge"/"skip"/"hayır" -> off; metinde mutlak yol varsa local + o yol. Tanınmazsa ("", "")."""
    text = " ".join(str(answer or "").split())
    m = _PATH_RE.search(text)
    if m:
        return "local", os.path.expanduser(m.group(1)).rstrip("/")
    low = text.casefold()
    if low.startswith(("yerel", "local")):
        return "local", ""
    if low.startswith(("uzak", "remote")):
        return "remote", ""
    if low.startswith(("vazge", "skip", "off", "hay", "no")):
        return "off", ""
    return "", ""


def prepare_copy(path: str, run: Optional[Callable] = None) -> Tuple[bool, str]:
    """Review öncesi yerel kopyayı güncelle: (ok, ileti). Kirli çalışma ağacı ya da `--ff-only` başarısızlığı = DUR
    (kullanıcının yerel değişikliği ezilmez, uzağa hiçbir şey yazılmaz)."""
    run = run or subprocess.run
    if not is_git_dir(path):
        return False, f"yerel kopya git deposu değil ya da yok: {path}"

    def git(*args: str) -> Tuple[int, str]:
        try:
            r = run(["git", "-C", path, *args], capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired) as e:
            return 1, str(e)
        return int(r.returncode), ((r.stdout or "") + (r.stderr or "")).strip()

    rc, out = git("status", "--porcelain")
    if rc != 0:
        return False, f"git status başarısız: {out[-300:]}"
    if out:
        return False, "yerel kopyada kaydedilmemiş değişiklik var; review başlamadı (önce temizle ya da commit'le)"
    rc, out = git("pull", "--ff-only")
    if rc != 0:
        return False, f"git pull --ff-only başarısız (çakışma/ayrışma?): {out[-300:]}"
    return True, out[-200:]


def eligible(choice_where: str, local_path: str) -> bool:
    """Uzak proje havuza girebilir mi: sahip yerel kopyayı seçti ve yol geçerli bir git deposu."""
    return choice_where == "local" and is_git_dir(local_path)
