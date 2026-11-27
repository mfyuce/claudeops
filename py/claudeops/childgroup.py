"""Zaman sınırlı yardımcı alt süreç (`--help` yoklaması, `mcp add`, tek atımlık çağrı, `agy models`, docker CLI) KENDİ yeni
süreç grubunda koşar; zaman aşımında (ya da kesilmede) grubun tamamı sonlandırılır, torunlar yetim kalmaz (TBD#397).

Oturum/CLI süreçleri buradan GEÇMEZ: onları yalnız `kill.py` sonlandırır. Sinyal yalnız bu işlevin az önce başlattığı ve
henüz beklemediği çocuğun grubuna gider; grup kimliği çağıranınkiyle aynıysa hiçbir gruba sinyal gönderilmez."""
from __future__ import annotations
import os
import signal
import subprocess
from typing import Any, Sequence


def _kill_group(proc: "subprocess.Popen[Any]") -> None:
    if proc.returncode is None:      # beklenmemiş çocuk: pid (ve grup kimliği) başkasına geçmiş olamaz
        try:
            pgid = os.getpgid(proc.pid)
            if pgid == proc.pid and pgid > 1 and pgid != os.getpgrp():
                os.killpg(pgid, signal.SIGKILL)
        except OSError:
            pass
    proc.kill()
    proc.wait()


def _run_grouped(argv: Sequence[str], *, timeout: float, capture_output: bool = False,
                 **kw: Any) -> "subprocess.CompletedProcess[Any]":
    """`subprocess.run(argv, timeout=...)` ile aynı sonuç ve istisnalar; fark: yeni oturum/süreç grubu ve grup sonlandırma."""
    if capture_output:
        kw.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with subprocess.Popen(argv, start_new_session=True, **kw) as proc:
        try:
            out, err = proc.communicate(timeout=timeout)
        except BaseException:        # zaman aşımı, Ctrl-C (ayrı grup terminal sinyalini almaz), çözümleme hatası
            _kill_group(proc)
            raise
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)
