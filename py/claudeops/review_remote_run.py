"""Uzak projede review koşusu (TBD#117 ek 3 (c), sahip kararı 2026-10-24): koşu uzak host'ta NORMAL bir ucli oturumunda yapılır
(anahtar taşınmaz, aynalama yok, uzak ağaca yazma yok), istem `term/input` ile gider, rapor `term/chat` (son asistan metni)
ile yerele çekilir.

Bu modül SAF orkestrasyon: `_execute`un beklediği `popen` sözleşmesini (`communicate`/`wait`/`poll`/`returncode`/`pid`)
sağlayan `RemoteReviewProc` + sürücü sözleşmesi. Gerçek uzak G/Ç (kapılar, `/api/start`, `term/input`, `term/chat`) sürücüde
(`web_steward.RemoteReviewDriver`); burada ağ ve `time` YOK (sleep/clock enjekte).

Sürücü sözleşmesi (hepsi `dict`, hata yutmaz):
  driver.start(model, effort) -> {ok, error?}        oturum açar (taze konuşma, salt-okunur); eski artık oturumu önce kapatır
  driver.send(text)           -> {ok, error?}
  driver.poll()               -> {running: bool|None, busy: bool|None, user: str, assistant: str}
  driver.stop()               -> None                (en iyi çaba)"""
from __future__ import annotations

import subprocess
import time
from typing import Any, Callable, Dict, Optional, Tuple

POLL_SECONDS = 10.0
MIN_WAIT_SECONDS = 20.0         # gönderimden sonra bu süre dolmadan "bitti" denmez (busy bayrağı henüz dönmemiş olabilir)
START_GRACE_SECONDS = 30.0      # gönderimden sonra bu süre içinde, henüz eşleşen yanıt yokken `running: False` ölü sayılmaz (oturum host listesinde belirmemiş olabilir)
STABLE_POLLS = 2                # busy=False + aynı cevap art arda bu kadar yoklamada görülürse bitti
HEAD_CHARS = 60


def _norm(s: str) -> str:
    return " ".join(str(s or "").split())


class RemoteReviewProc:
    """`subprocess.Popen` yerine geçen sahte süreç: `communicate(timeout)` uzak koşuyu sürer ve (rapor, hata) döner."""

    pid = None          # gerçek süreç değil: `_killpg` dokunmaz

    def __init__(self, driver: Any, model: str, effort: str, prompt: str, report_ok: Callable[[str], bool],
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 poll_seconds: Optional[float] = None, min_wait: Optional[float] = None,
                 start_grace: Optional[float] = None) -> None:
        self.driver, self.model, self.effort, self.prompt = driver, model, effort, prompt
        self.report_ok, self._sleep, self._clock = report_ok, sleep, clock
        self.poll_seconds = POLL_SECONDS if poll_seconds is None else poll_seconds    # çağrı anında okunur (testler küçültür)
        self.min_wait = MIN_WAIT_SECONDS if min_wait is None else min_wait
        self.start_grace = START_GRACE_SECONDS if start_grace is None else start_grace
        self.returncode: Optional[int] = None
        self._started = False
        self._sent_at = 0.0
        self._before = ""
        self._last = ""
        self._aborted = False
        self._error = ""

    # `_execute` / `cancel_key` arayüzü
    def poll(self) -> Optional[int]:
        return self.returncode

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        """`_terminate`un SIGTERM sonrası beklemesi: uzak oturumu kapat (kısmi metin `communicate`te kalır)."""
        self.abort()
        return self.returncode if self.returncode is not None else 1

    def terminate(self) -> None:
        self.abort()

    def abort(self) -> None:
        self._aborted = True
        self._stop()

    def _stop(self) -> None:
        try:
            self.driver.stop()
        except Exception:
            pass

    def _matches(self, st: Dict[str, Any]) -> bool:
        """Yoklanan değişim BİZİM istemimize mi ait (eski konuşmanın artığı değil)?"""
        head = _norm(self.prompt)[:HEAD_CHARS]
        user = _norm(st.get("user"))
        asst = str(st.get("assistant") or "")
        if head and head in user:
            return bool(asst.strip())
        return bool(asst.strip()) and asst != self._before

    def communicate(self, timeout: Optional[float] = None) -> Tuple[str, str]:
        if self._aborted:       # zaman aşımı / iptal sonrası ikinci çağrı: eldeki kısmi metin
            self.returncode = 1 if self.returncode is None else self.returncode
            return self._last, self._error or "aborted"
        deadline = None if timeout is None else self._clock() + float(timeout)
        if not self._started:
            res = self.driver.start(self.model, self.effort)
            if not res.get("ok"):
                self.returncode = 1
                return "", f"remote start: {res.get('error') or 'failed'}"
            self._started = True
            try:
                self._before = str((self.driver.poll() or {}).get("assistant") or "")
            except Exception:
                self._before = ""
            res = self.driver.send(self.prompt)
            if not res.get("ok"):
                self._stop()
                self.returncode = 1
                return "", f"remote send: {res.get('error') or 'failed'}"
            self._sent_at = self._clock()
        stable = 0
        prev = None
        while True:
            if self._aborted:
                break
            if deadline is not None and self._clock() > deadline:
                raise subprocess.TimeoutExpired("remote-review", timeout or 0)
            self._sleep(self.poll_seconds)
            try:
                st = self.driver.poll() or {}
            except Exception as e:     # tek yoklama hatası koşuyu öldürmez (host anlık bayat olabilir); zaman aşımı kapatır
                self._error = f"poll: {e!r}"
                continue
            matched = self._matches(st)
            if matched:
                self._last = str(st.get("assistant") or "")
            if st.get("running") is False and not (not matched and self._clock() - self._sent_at < self.start_grace):
                self._stop()
                self.returncode = 0 if (matched and self.report_ok(self._last)) else 1
                return self._last, ("" if self.returncode == 0 else (self._error or "remote session ended before a report"))
            if not matched or st.get("busy") is not False or self._clock() - self._sent_at < self.min_wait:
                stable, prev = 0, None
                continue
            stable = stable + 1 if prev == self._last else 1
            prev = self._last
            if stable >= STABLE_POLLS:
                self._stop()
                ok = self.report_ok(self._last)
                self.returncode = 0 if ok else 2
                return self._last, ("" if ok else "report format missing (no `## R-n |` heading, no 'BULGU YOK')")
        self.returncode = 1
        return self._last, self._error or "cancelled"
