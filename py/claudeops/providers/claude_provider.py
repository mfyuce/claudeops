"""claude CLI provider — bugüne kadarki tek/varsayılan davranış, aynen taşındı."""
from __future__ import annotations
import json
import os
import re
import shlex
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .base import CliProvider
from ..paths import PROJECTS_DIR

MODEL_CHOICES = [
    "claude-sonnet-5",
    "claude-opus-5",
    "claude-fable-5",
    "claude-haiku-4-5-20251001",
]
PERMISSION_MODES = ["auto", "acceptEdits", "bypassPermissions", "manual", "dontAsk", "plan"]
EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"]


def _encode_cwd(cwd: str) -> str:
    """CWD'yi project-dir encoding'e çevir — claude CLI'nın KENDİSİNİN
    `~/.claude/projects/` altında kullandığı adlandırma şemasını taklit eder.

    2026-09-05'te bulundu: eski hâli (sadece `/` ve `_` → `-`) ASCII-only
    cwd'ler için (yanlışlıkla) doğru sonuç veriyordu ama genel kural bu
    DEĞİLMİŞ — gerçek `~/.claude/projects/` dizin adlarıyla çapraz kontrol
    edilince (7 canlı örnek, bkz. commit) kuralın "harf/rakam OLMAYAN HER
    karakter → tek bir `-`" olduğu doğrulandı (Türkçe ğ/ü/ş/ı/ö/ç DAHİL —
    ör. ".../BLM308_veri_madenciliği" → ".../BLM308-veri-madencili-i", "ğ"
    de "-"e dönüşüyor). Eski hâli bu tür cwd'lerde (bu ortamda YAYGIN —
    Türkçe akademik proje klasörleri) YANLIŞ dizin adı üretip jsonl'ı hiç
    bulamıyordu — `find_latest_jsonl`/`resolve_resume_id`/`last_exchange`/
    `full_history`/`extra_file_roots`'un HEPSİ bunu kullandığı için sessizce
    etkileniyordu (resume-tespiti + Sohbet sekmesi + needs_ho + yeni dosya-
    gezgini kökü)."""
    return re.sub(r"[^a-zA-Z0-9]", "-", cwd)


def _safe_mtime(p: Path) -> float:
    """stat().st_mtime — concurrent deletion'a karşı fallback 0.0."""
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def find_latest_jsonl(cwd: str) -> Optional[Path]:
    """CWD için en son değiştirilen jsonl dosyasını döndür (resume sid için)."""
    encoded = _encode_cwd(cwd)
    proj_dir = Path(PROJECTS_DIR) / encoded
    if not proj_dir.exists():
        return None
    jsonls = [p for p in proj_dir.iterdir() if p.suffix == ".jsonl" and p.is_file()]
    return max(jsonls, key=_safe_mtime) if jsonls else None


def _arg(cmd: List[str], flag: str) -> Optional[str]:
    """cmdline listesinde `flag`'ten SONRAKİ değeri döndür (yoksa None)."""
    try:
        i = cmd.index(flag)
    except ValueError:
        return None
    return cmd[i + 1] if i + 1 < len(cmd) else None


def _extract_text(content) -> str:
    """message.content'ten düz metni çıkar — ya bir string ya da [{'type':'text',...},
    {'type':'tool_use',...}, ...] gibi bloklar listesi (tool_use/tool_result/image
    blokları YOK sayılır, sadece 'Sohbet' sekmesinde okunabilir metin göstermek için)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "\n\n".join(p for p in parts if p)
    return ""


def _is_real_user_text(content) -> bool:
    """Bir 'user' jsonl satırı gerçekten kullanıcının yazdığı bir mesaj mı, yoksa
    tool_result'un (bir önceki assistant tool_use'una otomatik cevap) 'user' rolüyle
    kodlanmış hali mi? tool_result bloğu varsa insan yazmamıştır, atla."""
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
    return False


class ClaudeProvider(CliProvider):
    name = "claude"

    def resolve_resume_id(self, cwd: str) -> Optional[str]:
        jsonl = find_latest_jsonl(cwd)
        return jsonl.stem if jsonl else None

    def build_inner_command(self, cwd, model, permission_mode, effort,
                             resume_id, prompt, session_name) -> str:
        # Mutlak yol (çıplak "claude" DEĞİL): bu string bir tmux pane'inin shell komutu
        # olarak çalışır, o pane'in PATH'i BİZİM PATH'imizden bağımsız — tmux server ilk
        # kez kuruluyorsa onu kuran her neyse (ör. systemd --user servisi, minimal PATH)
        # PATH'i miras kalır ve pane'de "claude: command not found" olur (canlı bulundu,
        # 2026-08-30). shutil.which BURADA (spawn'ı TETİKLEYEN sürecin PATH'inde) çözülüp
        # sonucu string'e gömülünce pane'in kendi PATH'i ne olursa olsun çalışır.
        binary = shutil.which("claude") or "claude"
        resume_arg = f"--resume {shlex.quote(resume_id)} " if resume_id else ""
        prompt_arg = f" {shlex.quote(prompt)}" if prompt else ""
        return (
            f"{shlex.quote(binary)} {resume_arg}"
            f"--model {shlex.quote(model)} "
            f"--permission-mode {shlex.quote(permission_mode)} "
            f"--effort {shlex.quote(effort)} "
            f"-n {shlex.quote(session_name)} "
            f"--remote-control {shlex.quote(session_name)}"
            f"{prompt_arg}"
        )

    def compact_command(self) -> Optional[str]:
        return "/compact"

    def handover_model_downgrade(self, current_model: str) -> Optional[str]:
        """2026-09-04, kullanıcı: "handover komutu öncesi model sonnet'e ve
        sonrası eski modele. seçili model daha düşükse kalsın." Canlı doğrulanan
        `/model` seçici metni (v2.1.260): Fable ("most capable for your hardest
        and longest-running tasks") ve Opus ("best for everyday, complex tasks")
        İKİSİ de Sonnet'ten ("efficient for routine tasks") YUKARIDA; Haiku
        ("fastest for quick answers") aşağıda. Tanınmayan/boş bir model adı
        GÜVENLİ VARSAYILANLA (dokunma → None) ele alınır — yanlış yönde bir
        swap (ör. gerçekte Sonnet'ten ucuz bir modeli yanlışlıkla Sonnet'e
        YÜKSELTMEK) maliyeti YANLIŞLIKLA artırır, bu asla olmamalı."""
        if not current_model:
            return None
        lowered = current_model.lower()
        if "opus" in lowered or "fable" in lowered:
            return "sonnet"
        return None

    _MODEL_SWITCH_TIMEOUT_SECONDS = 20.0
    _MODEL_SWITCH_POLL_SECONDS = 0.3

    def apply_live_model_switch(self, tmux_name: str, target_model: str) -> None:
        """`/model <target_model>` CANLI session'a gönderilir; bazen (ne zaman
        olduğu ÖNCEDEN KESTİRİLEMEZ, canlı test edildi — aynı 'meşgul' durumda
        bile TUTARSIZ) bir "Switch model?" onay diyaloğu açılıyor (konuşma
        cache'i kaybolacağı için). NAİF yaklaşım (gönder + SABİT bir süre
        bekle + kayıtsız-şartsız Enter) canlı testte GERÇEK bir mesaj kaybına
        yol açtı: dialog TAM o sabit bekleme penceresinin dışında açılınca,
        hemen ardından gönderilen bir SONRAKİ mesaj (bu durumda wrap-up mesajı)
        dialog'un kendisine yazılıp SESSİZCE kayboldu. Bunun yerine pane'i
        POLL'layıp dialog'un GERÇEKTEN açıldığını (veya hiç açılmadan direkt
        uygulandığını) DOĞRULUYOR — sadece dialog GÖRÜLÜNCE Enter gönderiyor.

        Bilinen KALAN sınır (canlı doğrulandı, kabul edilebilir bulundu):
        dialog'un açılması, session'ın O ANKİ turu bitirmesine bağlı — bir
        wrap-up turu bu timeout'tan (20s) UZUN sürerse (canlı testte 1m42s'e
        kadar görüldü), dialog bu fonksiyon döndükten SONRA açılabilir ve
        ONAYSIZ kalır. Bu ZARARSIZ bir kalıntı: dialog SONSUZA kadar geçerli
        kalıyor (canlı doğrulandı — dakikalar sonra gönderilen tek bir Enter
        bile temiz şekilde onaylıyor), session'ı BOZMUYOR, sadece o session
        bir sonraki etkileşime kadar model-değişikliği bekleyen bir dialog
        gösteriyor olabilir. Ana wrap-up mesajının kendisi bu riski TAŞIMAZ
        (`handover.py`/`web.py`'nin çağıran kodu ayrı bir yerleşme süresiyle
        bunu bilerek ayırıyor)."""
        from ..tmux_backend import tmux_capture, tmux_send_keys, tmux_send_special_key

        if not tmux_send_keys(tmux_name, f"/model {target_model}"):
            return
        deadline = time.monotonic() + self._MODEL_SWITCH_TIMEOUT_SECONDS
        dialog_confirmed = False
        while time.monotonic() < deadline:
            time.sleep(self._MODEL_SWITCH_POLL_SECONDS)
            text = tmux_capture(tmux_name, lines=20) or ""
            if not dialog_confirmed and "Switch model?" in text:
                tmux_send_special_key(tmux_name, "Enter")
                dialog_confirmed = True
                continue
            if "Set model to" in text or "Kept model as" in text:
                return
        if not dialog_confirmed:
            # Son bir şans: dialog belki tam bu son anda açıldı, henüz bir
            # sonraki poll turuna denk gelmedi — kör bir son Enter, dialog
            # yoksa (idle input kutusu) zaten kanıtlanmış zararsız bir no-op.
            tmux_send_special_key(tmux_name, "Enter")

    def matches_proc(self, cmd: List[str]) -> bool:
        """Bash `^claude` anchor'ının karşılığı: argv[0]'ın basename'i 'claude'.
        'bash -c "claude ..."' wrapper'ında argv[0]='bash' → eler."""
        return bool(cmd) and os.path.basename(cmd[0]) == "claude"

    def extract_name(self, proc, cmd: List[str]) -> Optional[str]:
        return _arg(cmd, "--remote-control")

    def extract_info(self, cmd: List[str]) -> Dict[str, Optional[str]]:
        return {
            "sid": _arg(cmd, "--resume"),
            "model": _arg(cmd, "--model"),
            "permission_mode": _arg(cmd, "--permission-mode"),
            "effort": _arg(cmd, "--effort"),
        }

    def model_choices(self) -> List[str]:
        return MODEL_CHOICES

    def permission_modes(self) -> List[str]:
        return PERMISSION_MODES

    def effort_levels(self) -> List[str]:
        return EFFORT_LEVELS

    def _transcript_lines(self, cwd: str, sid: Optional[str]) -> List[dict]:
        """`last_exchange`/`full_history`'nin PAYLAŞTIĞI adım: doğru jsonl'ı bul + parse
        edilmiş satırları döndür (bulunamazsa/okunamazsa boş liste — 'desteklenmiyor'
        ile 'henüz mesaj yok' ayrımı ÇAĞIRAN tarafın işi, burada değil).

        sid biliniyorsa (--resume ile başladıysa) TAM o dosya — aynı cwd'de birden fazla
        session paylaşıyorsa find_latest_jsonl (mtime) yanlış dosyayı seçebilir. sid yoksa
        (--new fresh start, Faz 2'nin varsayılanı) mtime fallback şart."""
        path: Optional[Path] = None
        if sid:
            candidate = Path(PROJECTS_DIR) / _encode_cwd(cwd) / f"{sid}.jsonl"
            if candidate.is_file():
                path = candidate
        if path is None:
            path = find_latest_jsonl(cwd)
        if path is None:
            return []
        try:
            lines = []
            with path.open(encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        lines.append(json.loads(raw))
                    except json.JSONDecodeError:
                        continue
            return lines
        except OSError:
            return []

    def last_exchange(self, cwd: str, sid: Optional[str]) -> Optional[Dict[str, str]]:
        # NOT: aşağıdaki "bulamadım" dallarının hepsi None DEĞİL boş dict döner —
        # None SADECE base.py'nin varsayılanında ("bu provider desteklemiyor") kalsın;
        # burada (claude provider'da) her zaman {"user":"","assistant":""} dönmek,
        # panelin "desteklenmiyor" ile "henüz mesaj yok" mesajlarını KARIŞTIRMAMASINI
        # sağlar (canlı bulundu: taze/boş bir session "bu CLI için sohbet görünümü
        # henüz yok" diye yanlış mesaj gösteriyordu — claude'un kendisi destekliyor,
        # sadece bu session'da henüz içerik yok).
        empty = {"user": "", "assistant": ""}
        lines = self._transcript_lines(cwd, sid)
        ai = None
        for i in range(len(lines) - 1, -1, -1):
            d = lines[i]
            if d.get("type") == "assistant" and not d.get("isSidechain"):
                ai = i
                break
        if ai is None:
            return empty
        assistant_text = _extract_text(lines[ai].get("message", {}).get("content"))
        user_text = ""
        for i in range(ai - 1, -1, -1):
            d = lines[i]
            if d.get("type") != "user" or d.get("isSidechain") or d.get("isMeta"):
                continue
            content = d.get("message", {}).get("content")
            if _is_real_user_text(content):
                user_text = _extract_text(content)
                break
        return {"user": user_text, "assistant": assistant_text}

    def extra_file_roots(self, cwd: str) -> List[Tuple[str, str]]:
        # find_latest_jsonl'ın AYNI encoding'i — dosya-gezginine bu proje için
        # claude'un kendi transcript/meta klasörünü (jsonl'lar dahil) ekler.
        return [("claude-transcripts", os.path.join(PROJECTS_DIR, _encode_cwd(cwd)))]

    def full_history(self, cwd: str, sid: Optional[str]) -> Optional[List[Dict[str, str]]]:
        # `last_exchange`'in tek-son-çift filtreleriyle AYNI kurallar (sidechain/isMeta/
        # tool_result-only hariç, boş metin hariç) — sadece SADECE SONUNCUYU almak yerine
        # sırayla HEPSİNİ biriktiriyor.
        out: List[Dict[str, str]] = []
        for d in self._transcript_lines(cwd, sid):
            t = d.get("type")
            if t == "assistant" and not d.get("isSidechain"):
                text = _extract_text(d.get("message", {}).get("content"))
                if text:
                    out.append({"role": "assistant", "text": text})
            elif t == "user" and not d.get("isSidechain") and not d.get("isMeta"):
                content = d.get("message", {}).get("content")
                if _is_real_user_text(content):
                    text = _extract_text(content)
                    if text:
                        out.append({"role": "user", "text": text})
        return out
