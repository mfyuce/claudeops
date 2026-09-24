"""ucli (unified-cli, ~/work/projects/tmp/unified-cli) rust agent'ını
subprocess pipe'ıyla konuşan, tmux'suz varsayılan yol — TOBEDECIDED#44(b).

Bilerek bir `CliProvider` DEĞİL (bkz. providers/base.py): o arayüz "uzun
ömürlü, etkileşimli bir tmux pane'i" varsayımı üzerine kurulu (spawn/discovery/
handover hepsi bunu varsayar), ucli'nin `chat --repl`/`chat --session` modları
ise düz stdin/stdout JSON-satırı yeterli, TTY'ye hiç dokunmuyor — kullanıcı
notu (2026-09-22): "claudeops her zaman tmux istemez, stdin'de [de] modlar
olsa iyi olur". tmux'lu (hidden=True, panelden canlı izlenebilir) bir yol
İSTENİRSE ShellProvider'ın deseni ayrıca eklenir; aynı gün ikinci bir netleşme
(kullanıcı): `--repl` hiçbir TTY-özel/raw-mode davranışına dokunmadığı için o
pane'de görülecek şey zaten sadece yazılan satır + JSON cevabın sırayla
ardışık akması — ayrı bir "girdi/çıktı" görünümü gerekmez. Bu modül o karardan
bağımsız, sadece pipe yolunu çözer.

İki mod:
- `ucli_chat_once()`: her çağrı ayrı process (`session=` verilirse ucli'nin
  kendi `.ucli/chat/NAME.jsonl`'ı üzerinden çağrılar arası hatırlar, verilmezse
  tamamen durumsuz) — nadir/ara sıra soru için, process-başlatma maliyeti
  önemsiz.
- `UcliReplSession`: TEK process açık kalır (`--repl`), turlar arasında
  `reqwest::Client` PAYLAŞILIR (TCP/TLS handshake tekrarlanmaz) — sık ardışık
  soru için. `ask()` bir prompt yazıp TEK JSON satırı okur; ucli'nin
  `main.rs`'i repl çıktısının HER turda tek-satır kompakt JSON olmasını
  garanti eder (2026-09-22'de burada bulunup unified-cli'de fixlendi —
  `--format`'ın pretty-print'i eskiden repl turlarını da 3 satıra
  yayıyordu, `output_with_style(..., pretty=False)` ile düzeltildi, bkz.
  unified-cli DONE.md/crates/ucli/tests/cli.rs'teki regresyon testi).

Protokolün kendi sınırı: `--repl` stdin'i SATIR satır okuyor, bir turun
cevabını request-id'siz eşliyor (sıraya güveniyor) — bu yüzden `ask()` bir
prompt içinde `\n` ya da boş satır kabul ETMEZ (ucli boş satırları sessizce
atlar, cevap gelmez → sıra kayar) ve timeout'ta session'ı KURTARMAYA
çalışmak yerine öldürür (gecikmiş bir cevap sıraya sonradan girip bir SONRAKİ
`ask()`'in cevabıymış gibi görünebilirdi — bkz. `_pump_stdout`).
"""
from __future__ import annotations
import json
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional


class UcliError(RuntimeError):
    """ucli'nin kendi `{"error": "..."}` turu ya da process/parse hatası."""


def resolve_binary(binary: Optional[str] = None) -> str:
    """`binary` verilmezse sırayla: `UCLI_BIN` env, PATH'te `ucli`, kardeş
    proje `~/work/projects/tmp/unified-cli`'nin debug/release build'i. Hiçbiri
    yoksa net bir hata — sessizce `FileNotFoundError: [Errno 2]` gibi
    anlaşılmaz bir subprocess istisnasına düşmek yerine.

    debug ÖNCE denenir: unified-cli'nin kendi README'si HER örnekte
    `target/debug/ucli`'yi çalıştırıyor (`cargo build --locked`, `--release`
    değil) — release'i önce denemek CANLI OLARAK yanlış çıktı: 2026-09-22'de
    `target/release/ucli` 5 gün eski bir build'di (`--session`/`--repl`
    eklenmeden ÖNCE), sessizce seçilip kafa karıştırıcı "unexpected argument
    '--repl'" hatası verdi. release'i hâlâ deniyoruz (biri gerçekten
    `--release` build edip debug'ı silerse diye) ama SADECE debug yoksa."""
    if binary:
        return binary
    env_bin = os.environ.get("UCLI_BIN")
    if env_bin:
        return env_bin
    found = shutil.which("ucli")
    if found:
        return found
    sibling = Path.home() / "work" / "projects" / "tmp" / "unified-cli" / "target"
    for profile in ("debug", "release"):
        candidate = sibling / profile / "ucli"
        if candidate.is_file():
            return str(candidate)
    raise UcliError(
        "ucli binary bulunamadı — UCLI_BIN ortam değişkenini ver, PATH'e ekle, "
        "ya da ~/work/projects/tmp/unified-cli'de `cargo build --locked` çalıştır."
    )


def build_chat_argv(
    binary: str,
    root: str,
    *,
    repl: bool,
    session: Optional[str],
    model: Optional[str],
    endpoint: Optional[str],
    api_key_env: str,
    with_mcp: bool,
    max_steps: Optional[int],
) -> list[str]:
    argv = [binary, "--root", root, "chat"]
    if repl:
        argv.append("--repl")
    if session:
        argv += ["--session", session]
    if model:
        argv += ["--model", model]
    if endpoint:
        argv += ["--endpoint", endpoint]
    if api_key_env:
        argv += ["--api-key-env", api_key_env]
    if with_mcp:
        argv.append("--with-mcp")
    if max_steps is not None:
        argv += ["--max-steps", str(max_steps)]
    return argv


def _subprocess_env(api_key_env: str, api_key: Optional[str]) -> Optional[Dict[str, str]]:
    """`api_key` verilirse (ör. bir web formundan) `subprocess`'e geçilecek
    TAM env kopyası — `api_key_env` adlı değişkeni ekler/override eder,
    sürecin kendi ortamına kalıcı yazmaz. `api_key` verilmezse None (=
    `Popen`/`run`'ın kendi varsayılanı: ebeveyn env'i DEĞİŞTİRMEDEN miras al)
    — bugüne kadarki davranış birebir korunur, sadece YENİ bir çağıran
    (ör. web formu) açıkça bir anahtar geçtiğinde devreye girer."""
    if api_key is None:
        return None
    return {**os.environ, api_key_env: api_key}


def chat_session_dir(cwd: str) -> str:
    """`.ucli/chat/*.jsonl`'ın yaşadığı proje-başına dizin — `io_providers/
    ucli_provider.py` (tmux'suz `IoProvider`) ve `providers/ucli_provider.py`
    (tmux-backed `CliProvider`) AYNI klasörü/dosya biçimini okur: ikisi de aynı
    `--session NAME` kavramını paylaşıyor, sadece süreç yönetimi (Python'ın
    kendi pipe'ı vs. tmux pane) farklı."""
    return os.path.join(cwd, ".ucli", "chat")


def read_chat_history(cwd: str, session: str) -> Optional[List[Dict[str, str]]]:
    """`{session}.jsonl`'ı `[{"role":..., "text":...}, ...]`'a çevirir.
    Dosya yoksa boş liste (henüz mesaj yok, hata değil) — okunamaz/bozuksa
    `None` (çağıran "desteklenmiyor" ile "henüz mesaj yok"u ayırabilsin)."""
    path = os.path.join(chat_session_dir(cwd), f"{session}.jsonl")
    if not os.path.isfile(path):
        return []
    turns: List[Dict[str, str]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                turn = json.loads(line)
                turns.append({"role": turn["role"], "text": turn["content"]})
    except (OSError, json.JSONDecodeError, KeyError):
        return None
    return turns


def _parse_turn(line: str) -> Dict[str, Any]:
    line = line.strip()
    if not line:
        raise UcliError("ucli hiçbir çıktı vermeden kapandı")
    try:
        value = json.loads(line)
    except json.JSONDecodeError as e:
        raise UcliError(f"ucli çıktısı tek-satır JSON değildi: {e}\nsatır={line!r}") from e
    if "error" in value:
        raise UcliError(value["error"])
    return value


def ucli_chat_once(
    root: str,
    prompt: str,
    *,
    session: Optional[str] = None,
    model: Optional[str] = None,
    endpoint: Optional[str] = None,
    api_key_env: str = "UCLI_API_KEY",
    api_key: Optional[str] = None,
    with_mcp: bool = False,
    max_steps: Optional[int] = None,
    binary: Optional[str] = None,
    timeout: float = 120.0,
) -> Dict[str, Any]:
    """Tek görev, tek process. Dönen dict `{"answer", "model_rounds",
    "tool_calls"}` (`AgentAnswer`, agent.rs) — `chat` (repl'siz) hep pretty-
    printed JSON yazar ama `json.loads` boşluğa bakmaz, framing derdi yok
    (process ömrü boyunca TEK değer). `api_key` verilirse (çağıranın kendi
    ortamına güvenmek yerine, ör. bir web formundan) bkz. `_subprocess_env`."""
    argv = build_chat_argv(
        resolve_binary(binary), root, repl=False, session=session, model=model,
        endpoint=endpoint, api_key_env=api_key_env, with_mcp=with_mcp,
        max_steps=max_steps,
    )
    argv.append(prompt)
    env = _subprocess_env(api_key_env, api_key)
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as e:
        raise UcliError(f"ucli {timeout}s içinde cevap vermedi") from e
    if result.returncode != 0:
        raise UcliError(result.stderr.strip() or f"ucli exit={result.returncode}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise UcliError(f"ucli çıktısı JSON değildi: {e}\nstdout={result.stdout!r}") from e
    if "error" in value:
        raise UcliError(value["error"])
    return value


class UcliReplSession:
    """`ucli chat --repl` etrafında ince bir sarmalayıcı — TEK process,
    stdin/stdout PIPE (tmux YOK, ANSI/capture-pane derdi yok).

    Arka planda TEK kalıcı reader thread stdout'u bir `Queue`'ya pompalar
    (session ömrü boyunca) — `ask()` başına thread AÇMIYOR: iki thread'in
    aynı stdout'u eşzamanlı okuması, bir timeout'tan SONRA gecikmiş cevabın
    bir SONRAKİ `ask()`'e yanlış eşlenmesi riski taşırdı. Onun yerine bir
    `ask()` timeout'a uğrarsa process'i doğrudan öldürür (`_ask` bkz.) —
    protokolün request-id'si yok, gecikmiş bir cevabı güvenle "bu turdu"
    diye damgalamanın yolu yok, o yüzden kurtarmaya çalışmak yerine session'ı
    kesin-ölü sayıyoruz.

    Thread-safe: `ask()` kilit tutuyor, paralel çağrılar sıraya girer
    (aynı process'e paralel yazmak/okumak zaten anlamsız — ucli turları TEK
    process içinde sıralı işliyor).
    """

    def __init__(
        self,
        root: str,
        *,
        session: Optional[str] = None,
        model: Optional[str] = None,
        endpoint: Optional[str] = None,
        api_key_env: str = "UCLI_API_KEY",
        api_key: Optional[str] = None,
        with_mcp: bool = False,
        max_steps: Optional[int] = None,
        binary: Optional[str] = None,
    ) -> None:
        argv = build_chat_argv(
            resolve_binary(binary), root, repl=True, session=session, model=model,
            endpoint=endpoint, api_key_env=api_key_env, with_mcp=with_mcp,
            max_steps=max_steps,
        )
        self._proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=_subprocess_env(api_key_env, api_key),
        )
        self._lock = threading.Lock()
        self._lines: "queue.Queue[str]" = queue.Queue()
        self._reader = threading.Thread(target=self._pump_stdout, daemon=True)
        self._reader.start()

    def _pump_stdout(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            self._lines.put(line)
        self._lines.put("")  # EOF sentinel — ucli'nin gerçek turları hiç boş satır basmaz

    def ask(self, prompt: str, timeout: float = 120.0) -> Dict[str, Any]:
        prompt_line = prompt.strip()
        if not prompt_line:
            raise UcliError("boş prompt gönderilemez (ucli --repl boş satırları atlar, cevap gelmez)")
        if "\n" in prompt:
            raise UcliError(
                "prompt tek satır olmalı (--repl stdin'i satır satır okur); "
                "çok satırlı metni çağıran kendi kararıyla tek satıra indirsin"
            )
        if prompt_line == "/exit":
            raise UcliError("'/exit' ask() ile gönderilmez, close() kullan")
        with self._lock:
            if self._proc.poll() is not None:
                raise UcliError(f"ucli repl process zaten kapanmış (exit={self._proc.returncode})")
            assert self._proc.stdin is not None
            self._proc.stdin.write(prompt_line + "\n")
            self._proc.stdin.flush()
            try:
                line = self._lines.get(timeout=timeout)
            except queue.Empty:
                self._proc.kill()  # bkz. sınıf docstring'i: gecikmiş cevabı güvenle eşleyemeyiz
                raise UcliError(f"ucli {timeout}s içinde cevap vermedi, session öldürüldü")
        if line == "":
            stderr = self._proc.stderr.read() if self._proc.stderr else ""
            raise UcliError(f"ucli repl beklenmedik şekilde kapandı: {stderr.strip()}")
        return _parse_turn(line)

    def close(self, timeout: float = 5.0) -> None:
        if self._proc.poll() is not None:
            return
        try:
            with self._lock:
                if self._proc.stdin:
                    self._proc.stdin.write("/exit\n")
                    self._proc.stdin.flush()
            self._proc.wait(timeout=timeout)
        except Exception:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=timeout)
            except Exception:
                self._proc.kill()

    def __enter__(self) -> "UcliReplSession":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
