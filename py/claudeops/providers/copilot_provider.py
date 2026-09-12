"""copilot (GitHub Copilot CLI) provider.

Farklar (agy/codex'e göre, ikisi de en yakın emsal):
- `--remote-control`/isimlendirme bayrağı YOK → agy/codex gibi `COPS_NAME` env'iyle
  çözülüyor (spawn'da set edilir, discovery'de `psutil.Process.environ()` ile okunur).
- Resume/transcript kaynağı `~/.copilot/session-store.db` (SQLite) — agy'nin ŞEMASIZ
  protobuf'ının AKSİNE düz/okunabilir bir şema (canlı doğrulandı, 2026-09-13, `.schema`
  + gerçek satırlar): `sessions(id, cwd, ...)` + `turns(session_id, turn_index,
  user_message, assistant_response, ...)`. Bu yüzden `last_exchange`/`full_history`
  agy'nin reverse-engineering'ini GEREKTİRMEDİ, düz SQL yeterli — ilk planın "SQLite
  şeması bilinmiyor, ertelensin" varsayımı yanlış çıktı, şema kendi kendini anlatıyordu.
- Model listesi CANLI çekilecek bir KOMUT yok (`agy models`/codex'in `models_cache.json`
  dosyasının muadili bulunamadı — `~/.copilot/data.db`'nin `provider_models` tablosu BOŞ)
  ama ⚠ **2026-09-13 düzeltme: ilk sürümün "sadece 1 model" varsayımı YANLIŞTI** — canlı
  komut yok ama interaktif `/model` bir SEÇİCİ açıyor ve o seçici hesabın GERÇEK ~19
  modelini listeliyor (canlı doğrulandı, izole scratch session, `/model` + capture-pane).
  `MODEL_CHOICES` şimdi bu seçiciden görülen isimlerden türetildi — ama 4'ü DIŞINDA HİÇBİRİ
  (17 model, 13'ü doğrulanmadı) tek tek seçilip config.json/status çubuğuyla doğrulanmadı
  (4'ü: `gpt-5.4` orijinal `--model gpt-5.4` spawn'ıyla, `gpt-5.6-terra`/`claude-sonnet-5`
  seçiciden seçilip config.json'a yazıldığı GÖRÜLEREK, `gemini-3.8-flash` ise doğrudan
  `--model gemini-3.8-flash` spawn'ıyla — status çubuğu "Gemini 3.8 Flash" gösterdi,
  fallback YOKTU). Geri kalanlar
  seçicinin GÖRÜNEN İSİMLERİNDEN aynı desenle (küçük harf, boşluk→tire, NOKTALAR
  KORUNUYOR — "GPT-5.6 Terra"→`gpt-5.6-terra`, nokta tireye ÇEVRİLMİYOR, doğrulanan 2
  örnekte de böyle) türetildi, TEK TEK doğrulanmadı. "Unavailable models" başlığı altında
  görülen 2 model (`gpt-5.6-sol`, `gpt-5.5`) BİLEREK listeye EKLENMEDİ (seçicinin kendisi
  bunları kullanılamaz işaretliyor). CLI geçersiz bir `--model` değerine karşı İKİ FARKLI
  davranış gösteriyor (canlı doğrulandı): interaktif modda SESSİZCE en yakın geçerli
  modele düşüyor + bir uyarı basıyor ("Model \"X\" ... not available. Using \"gpt-5.4\"
  instead."), ama `-p` (headless) modda SERT hata verip hiç başlamıyor. claudeops HER
  ZAMAN interaktif spawn ettiği için (tmux pane, `-p` değil) buradaki 13 doğrulanmamış
  tahminden biri yanlış çıksa bile spawn ÇÖKMÜYOR — sadece kullanıcı beklemediği bir
  modele düşebilir, bu yüzden hepsini tek tek doğrulamadan eklemek (agy/codex'in
  "küçük/özel hesap roster'ı" ile AYNI kabul edilebilir risk sınıfı) "sadece 1 model
  var" göstermekten kesinlikle daha iyi (canlı kullanıcı raporu: "model listesinde
  sadece iki tane var 10 parca olmalı idi").
- effort `--effort`/`--reasoning-effort <low|medium|high|xhigh>` (agy/codex'in ayrı
  flag'ine benzer, ikisi AYNI bayrağın takma adı).
- permission_mode `--mode interactive|plan|autopilot` (BAŞLANGIÇ modu) + `--allow-all-tools
  --allow-all-paths --allow-all-urls` (ya da tek başına `--allow-all`/`--yolo`) — dört isme
  eşleniyor (aşağıya bkz., agy/codex'in `_PERMISSION_FLAGS` desenindeki gibi).
- Canlı mod OKUMA sadece "plan"/"autopilot" için var: durum çubuğunda `· plan ·`/
  `· autopilot ·` literal metni (canlı doğrulandı, izole scratch session, hem `--mode plan`
  hem `--autopilot` ayrı ayrı spawn edilip capture-pane ile gözlemlendi). "interactive"
  (varsayılan) modun kendine özgü bir işareti YOK — durum çubuğu nötr/farklı bir görünümde
  (banner/hint metni, mod adı hiç geçmiyor) — bu yüzden `mode_status_patterns()`'ta YOK,
  hiçbiri eşleşmezse "bilinmiyor" sayılması zaten doğru davranış (claude'un "her modun
  kendi metni var" iddiasının AKSİNE, burada gerçekten işaretsiz bir mod var).
  `cyclable_modes()` BİLEREK boş bırakıldı: claude'un Shift+Tab CANLI döngüsünün bir
  muadili GÖZLEMLENMEDİ (`--help`'te böyle bir tuş kombinasyonu belgeli değil, mod
  başlatma-zamanı bir seçim gibi görünüyor) — canlı kanıt olmadan icat edilmedi.
- Busy sinyali durum çubuğundaki "Esc to cancel" (claude'un "esc to interrupt"ının
  muadili) — canlı doğrulandı: hem düz metin sorusunda ("Thinking") hem bir shell-tool
  çağrısında görünüyor, idle'da tamamen kayboluyor.
- **Bilinen kısıtlama, bu pass'te ÇÖZÜLMEDİ:** bir cwd'de İLK KEZ çalıştırıldığında
  interaktif bir "Confirm folder trust" diyaloğu açılıyor (canlı doğrulandı) — bunu
  bypass eden bir CLI bayrağı YOK (`--help` tam taranmış, `--allow-all`/`--allow-all-paths`
  bile bunu atlamıyor). "2. Yes, and remember this folder for future sessions" seçilirse
  o cwd için BİR DAHA sorulmuyor (`~/.copilot/config.json`'ın `trustedFolders` listesine
  yazılıyor, canlı doğrulandı) — yani sorun SADECE bir projenin claudeops üzerinden İLK
  spawn'ında çıkar, sonraki respawn'larda YOK. Otomatik cevaplama (spawn sonrası kör bir
  "2\\n" enjeksiyonu) bu pass'te EKLENMEDİ — "her zaman aynı diyalog aynı sırada mı çıkıyor"
  varsayımı kanıtsız (ör. `.github/agents` güvenilir-config'i olan bir repo'da hiç
  çıkmayabilir, ya da diyalog metni/seçenek sırası bir CLI güncellemesiyle değişebilir);
  TODO.md'ye ayrı bir madde olarak işlendi.
- `compact_command()` BİLEREK None (varsayılan) bırakıldı: `/compact` interaktif komut
  listesinde GERÇEKTEN var (`copilot help commands`, claude'unkiyle aynı isim) ama
  base.py'nin kendi docstring'i şunu açıkça uyarıyor: bu metod SADECE gate'i polimorfik
  yapar, `web.py`'nin `_compact()`'inin HEADLESS ÇAĞRISI hâlâ claude'a özgü bir argv/binary
  şekli varsayıyor (`shutil.which("claude")` sabit). Burada "/compact" döndürmek gate'i
  açar ama invocation'ı düzeltmez → gate açık, gerçek çağrı yanlış binary'ye gider gibi
  YARIM/BOZUK bir özellik olurdu. `_compact()`'in kendisi genellenmeden bu AÇILMAMALI —
  base.py'nin "ikinci veri noktası olmadan spekülatif genelleme yok" ilkesiyle aynı yerde
  duruyor, TODO.md'ye not düşüldü.
- `mcp_launch_args`/`mcp_setup_command` BİLEREK boş/None (varsayılan) bırakıldı:
  `--additional-mcp-config <json|@file>` per-invocation bir yol GİBİ duruyor (claude'un
  `--mcp-config <dosya>`'sına benzer) ama GERÇEK bir MCP server'a karşı bu pass'te CANLI
  DOĞRULANMADI (zaman/kapsam kısıtı) — base.py'nin "yok=boş, sadece kanıtlanan destekleyen
  override eder" ilkesine göre spekülatif eklenmedi, TODO.md'ye not düşüldü.
- `apply_live_model_switch`/`handover_model_downgrade` BİLEREK varsayılan (no-op/None)
  bırakıldı: copilot'un KENDİ `/model` interaktif komutu var ama davranışı (argüman kabul
  ediyor mu, bir seçici mi açıyor, onay diyaloğu var mı) CANLI DOĞRULANMADI — claude'un
  aynı alanda (bkz. `ClaudeProvider.apply_live_model_switch`) kanıtsız bir ilk deneme
  YANLIŞ ÇIKIP canlı veri kaybına yol açtığı bir tarihi var, o dersle aynı temkin.
- BYOK (bring-your-own-key, ör. DeepSeek/Ollama/Azure): `env_overrides()` `COPS_NAME`'e
  EK olarak `settings.byok_env_for("copilot")`'ı da enjekte eder — `settings.json`'ın
  `byok.copilot` alanına `COPILOT_PROVIDER_BASE_URL`/`_API_KEY`/`COPILOT_MODEL` gibi
  env'ler elle yazılırsa, copilot'un KENDİ resmi BYOK mekanizması (`copilot help
  providers` — örneklerinden biri LİTERALEN `deepseek-coder-v2:16b`, Ollama üzerinden)
  devreye girip GitHub'ın kendi model-routing'i yerine o endpoint'i kullanır — bu yüzden
  DeepSeek AYRI bir provider/CLI GEREKTİRMİYOR (bu makinede bağımsız bir `deepseek` CLI'ı
  da yok, aranıp doğrulandı). Ayarlar sekmesinde bunu düzenleyecek bir UI alanı BİLEREK
  YOK — bkz. `settings.py`'nin `byok` yorumu.
"""
from __future__ import annotations
import os
import re
import shlex
import sqlite3
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

from .base import CliProvider, McpServerSpec
from ..settings import byok_env_for, resolved_binary

SESSION_STORE_DB = os.path.expanduser("~/.copilot/session-store.db")

# Modül docstring'indeki 2026-09-13 düzeltmesine bkz.: `/model` seçicisinden
# görülen ~19 modelden "Unavailable" iki tanesi çıkarılmış hali — sadece
# gpt-5.4/gpt-5.6-terra/claude-sonnet-5 tek tek doğrulandı, gerisi görünen
# isimden aynı desenle türetildi (yanlış çıksa bile interaktif spawn'da
# sessizce en yakın modele düşer, çökmez).
MODEL_CHOICES = [
    "gpt-5.6-terra",       # doğrulandı (config.json recentModelIds)
    "claude-sonnet-5",     # doğrulandı (config.json recentModelIds)
    "gemini-3.8-flash",
    "grok-4.6",
    "gpt-5.6-luna",
    "gpt-5.4",             # doğrulandı (orijinal --model gpt-5.4 spawn)
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5-mini",
    "claude-haiku-4.5",
    "mai-code-1.1-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "grok-4.5",
    "kimi-k3",
    "kimi-k2.7-code",
]
PERMISSION_MODES = ["auto", "manual", "plan", "autopilot"]
EFFORT_LEVELS = ["low", "medium", "high", "xhigh"]

# Durum çubuğunda `· plan ·` / `· autopilot ·` literal metni (canlı doğrulandı) —
# `·` ayraçlarıyla ÇEVRİLİ olması, session'ın ürettiği rastgele metinde geçen bir
# "plan" kelimesiyle yanlışlıkla eşleşmeyi engelliyor (claude'un ANSI-per-word
# dersiyle aynı sınıf temkin, burada farklı bir yanlış-eşleşme riski için).
MODE_STATUS_PATTERNS = {
    "plan": r"·\s*plan\s*·",
    "autopilot": r"·\s*autopilot\s*·",
}
BUSY_STATUS_PATTERN = r"Esc to cancel"

_PERMISSION_FLAGS = {
    "auto": ["--allow-all-tools", "--allow-all-paths", "--allow-all-urls"],
    "manual": [],
    "plan": ["--mode", "plan"],
    "autopilot": ["--autopilot", "--allow-all-tools", "--allow-all-paths", "--allow-all-urls"],
}

_RESUME_SCAN_LIMIT = 500  # session-store.db tek dosya/hafif ama sınırsız taramaya gerek yok

# `/usage`'ın çıktısı (canlı doğrulandı, 2026-09-13, izole scratch session):
#    Plan       ■■■■■■■■■■■■■■■■■■■■ 0% used
#               11 / 1,500 AIC
# claude'un "Current session"/"Current week (...)" gibi BİRDEN FAZLA satırının
# aksine tek bir "Plan" satırı var (hesap tek bir AI-Credit havuzu kullanıyor
# gibi duruyor) — o yüzden claude'un çok-satır-tarama döngüsüne gerek yok,
# tek geçişte iki regex yeterli.
_USAGE_PLAN_RE = re.compile(r"Plan\s+\S*\s*(\d+)%\s*used")
_USAGE_FRACTION_RE = re.compile(r"([\d,]+\s*/\s*[\d,]+\s*AIC)")


def _arg(cmd: List[str], flag: str) -> Optional[str]:
    try:
        i = cmd.index(flag)
    except ValueError:
        return None
    return cmd[i + 1] if i + 1 < len(cmd) else None


def _connect_ro() -> sqlite3.Connection:
    # mode=ro: SADECE okuma — copilot'un kendi canlı DB'sine (aktif yazılıyor
    # olabilir) yanlışlıkla dokunmak/var-olmayan bir dosya yaratmak İSTENMİYOR
    # (agy_provider.py'deki AYNI gerekçe/desen).
    return sqlite3.connect(f"file:{SESSION_STORE_DB}?mode=ro", uri=True, timeout=2.0)


class CopilotProvider(CliProvider):
    name = "copilot"

    def resolve_resume_id(self, cwd: str, in_use: FrozenSet[str] = frozenset(),
                          session_name: str = "") -> Optional[str]:
        """`sessions.cwd` doğrudan bir sütun (agy/codex'in cwd'yi cache/rollout
        içinden ayrıca çıkarması GEREKMİYOR) — en son güncellenen (`updated_at`)
        eşleşen session, `in_use` kümesindeki id'ler HARİÇ (claude/agy/codex'le
        AYNI 2026-09-07 çift-resume güvenliği). copilot'un session'ları bir
        isim/başlık taşımıyor (`session_name` bu yüzden claude'daki gibi bir
        tercih sinyali olarak KULLANILMIYOR, agy'nin cwd-tekil-cache'i gibi)."""
        target = os.path.normpath(os.path.abspath(cwd))
        try:
            conn = _connect_ro()
            try:
                rows = conn.execute(
                    "SELECT id, cwd FROM sessions ORDER BY updated_at DESC LIMIT ?",
                    (_RESUME_SCAN_LIMIT,),
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return None
        for sid, raw_cwd in rows:
            if not raw_cwd or os.path.normpath(os.path.abspath(str(raw_cwd))) != target:
                continue
            if sid in in_use:
                continue
            return sid
        return None

    def build_inner_command(self, cwd, model, permission_mode, effort,
                             resume_id, prompt, session_name, extra_args: Sequence[str] = ()) -> str:
        # Mutlak yol — claude/agy/codex provider'larındaki AYNI fix'in yorumu
        # (pane'in kendi PATH'i tmux server'ın miras kaldığından farklı/eksik olabilir).
        binary = resolved_binary("copilot")
        parts = [shlex.quote(binary)]
        if resume_id:
            parts += ["--resume", shlex.quote(resume_id)]
        parts += ["--model", shlex.quote(model)]
        parts += ["--effort", shlex.quote(effort or "medium")]
        parts += _PERMISSION_FLAGS.get(permission_mode or "auto", _PERMISSION_FLAGS["auto"])
        parts += [shlex.quote(a) for a in extra_args]
        if prompt:
            parts += ["-i", shlex.quote(prompt)]
        return " ".join(parts)

    def env_overrides(self, session_name: str) -> Dict[str, str]:
        env = {"COPS_NAME": session_name}
        env.update(byok_env_for("copilot"))
        return env

    def matches_proc(self, cmd: List[str]) -> bool:
        return bool(cmd) and os.path.basename(cmd[0]) == "copilot"

    def extract_name(self, proc, cmd: List[str]) -> Optional[str]:
        try:
            name = proc.environ().get("COPS_NAME")
        except Exception:
            name = None
        return name or f"copilot-{proc.pid}"

    def extract_info(self, cmd: List[str]) -> Dict[str, Optional[str]]:
        if "--autopilot" in cmd or _arg(cmd, "--mode") == "autopilot":
            permission_mode = "autopilot"
        elif _arg(cmd, "--mode") == "plan":
            permission_mode = "plan"
        elif any(f in cmd for f in ("--allow-all-tools", "--allow-all", "--yolo")):
            permission_mode = "auto"
        else:
            permission_mode = "manual"
        return {
            "sid": _arg(cmd, "--resume"),
            "model": _arg(cmd, "--model"),
            "permission_mode": permission_mode,
            "effort": _arg(cmd, "--effort") or _arg(cmd, "--reasoning-effort"),
        }

    def model_choices(self) -> List[str]:
        return MODEL_CHOICES

    def permission_modes(self) -> List[str]:
        return PERMISSION_MODES

    def effort_levels(self) -> List[str]:
        return EFFORT_LEVELS

    def mode_status_patterns(self) -> Dict[str, str]:
        return MODE_STATUS_PATTERNS

    def busy_status_pattern(self) -> Optional[str]:
        return BUSY_STATUS_PATTERN

    def usage_command(self) -> Optional[str]:
        return "/usage"

    # usage_needs_dismiss(): base.py'nin varsayılanı (False) KORUNUYOR —
    # copilot'un `/usage`'ı MODAL değil, kalıcı bir yan-panel (canlı
    # doğrulandı, 2026-09-13: Escape gönderiminin ekranda GÖZLE GÖRÜLÜR
    # hiçbir etkisi olmadı, panel açık kaldı) — claude'un aksine kapatma
    # GEREKMİYOR.

    def parse_usage_text(self, text: str) -> Optional[List[Dict[str, str]]]:
        m = _USAGE_PLAN_RE.search(text)
        if not m:
            return None
        fm = _USAGE_FRACTION_RE.search(text, m.end())
        return [{"label": "Plan (AI Credits)", "percent": m.group(1), "detail": fm.group(1) if fm else ""}]

    def _turns(self, cwd: str, sid: Optional[str]) -> List[Tuple[str, str]]:
        """`last_exchange`/`full_history`'nin PAYLAŞTIĞI adım — claude/codex'in
        `_transcript_lines`/agy'nin `_transcript_steps`'iyle AYNI sözleşme:
        bulunamazsa/okunamazsa boş liste, 'desteklenmiyor' ile 'henüz mesaj yok'
        ayrımı ÇAĞIRAN tarafın işi. `sid` yoksa `resolve_resume_id` ile cwd'den
        çözülür (aynı `--resume` argümanının spawn-zamanındaki çözümü)."""
        session_id = sid or self.resolve_resume_id(cwd)
        if not session_id:
            return []
        try:
            conn = _connect_ro()
            try:
                rows = conn.execute(
                    "SELECT user_message, assistant_response FROM turns "
                    "WHERE session_id = ? ORDER BY turn_index",
                    (session_id,),
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return []
        return [(u or "", a or "") for u, a in rows]

    def last_exchange(self, cwd: str, sid: Optional[str]) -> Optional[Dict[str, str]]:
        # claude/agy/codex'le AYNI "her zaman dict, None değil" sözleşmesi — None
        # SADECE base.py'nin "desteklenmiyor" varsayılanında kalsın diye.
        turns = self._turns(cwd, sid)
        if not turns:
            return {"user": "", "assistant": ""}
        user, assistant = turns[-1]
        return {"user": user, "assistant": assistant}

    def full_history(self, cwd: str, sid: Optional[str]) -> Optional[List[Dict[str, str]]]:
        # last_exchange'in tek-son-çift filtreleriyle AYNI kurallar (boş metin
        # hariç) — SADECE SONUNCUYU almak yerine sırayla HEPSİNİ biriktirir.
        out: List[Dict[str, str]] = []
        for user, assistant in self._turns(cwd, sid):
            if user:
                out.append({"role": "user", "text": user})
            if assistant:
                out.append({"role": "assistant", "text": assistant})
        return out
