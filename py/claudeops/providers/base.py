"""CLI provider arayüzü — her yönetilen CLI (claude, agy, ...) bu sınıfı doldurur.

Manager kod (spawn.py/discovery.py/commands/web.py) YALNIZCA bu arayüz
üzerinden çağırır; hiçbir yerde `if cli == "agy"` dallanması OLMAMALI —
yeni bir CLI eklemek yeni bir provider dosyası + registry'ye bir satır demek.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

import psutil


class CliProvider(ABC):
    name: str  # "claude" | "agy" | ...

    # ── spawn tarafı ─────────────────────────────────────────────────────────

    @abstractmethod
    def resolve_resume_id(self, cwd: str) -> Optional[str]:
        """cwd için devam edilecek konuşma/sid'i bul (yoksa None → fresh/new)."""

    @abstractmethod
    def build_inner_command(
        self,
        cwd: str,
        model: str,
        permission_mode: str,
        effort: str,
        resume_id: Optional[str],
        prompt: Optional[str],
        session_name: str,
    ) -> str:
        """SADECE `<binary> ...` çağrısı (ör. `agy --model ... --effort ...`) — `cd CWD &&`
        ÖNEKİNİ YAZMA, onu `spawn_session` ekler (env_overrides'ı doğru yere — cd'den
        SONRA, binary çağrısından HEMEN ÖNCE — enjekte edebilmek için, bkz. aşağı)."""

    def has_conversation(self) -> bool:
        """True (varsayılan) = provider bir 'konuşma' sürdürüyor → handover Faz1
        (wrap-up mesajı + kill/resume) ve stuck-recovery bu session'ı hedefler.
        False → düz bir shell gibi konuşma kavramı olmayan provider'lar için: Faz1/
        stuck bu session'ı asla öldürmez/yeniden açmaz (isimle bile hedeflense),
        çünkü kill edecek "konuşma" yok, sadece kullanıcının canlı terminal'i var."""
        return True

    def last_exchange(self, cwd: str, sid: Optional[str]) -> Optional[Dict[str, str]]:
        """Son user mesajı + son assistant yanıtını {'user':..., 'assistant':...} olarak
        döndür — panelin terminal-popup'ındaki 'Sohbet' sekmesi için (capture-pane/ANSI
        yerine STRUCTURED veri: xterm.js'in mobilde scroll/render sorunlarını [[terminal
        canlı yaşanan raporlar]] tamamen bypass eder). None = bu CLI için desteklenmiyor
        (panel "henüz yok" gösterir, hata değil) — varsayılan budur, sadece jsonl/DB gibi
        okunabilir bir transcript'i olan provider'lar (claude) override eder."""
        return None

    def full_history(self, cwd: str, sid: Optional[str]) -> Optional[List[Dict[str, str]]]:
        """`last_exchange`'in TEK son çifti yerine TÜM gerçek user/assistant turlarını
        sırayla [{'role':'user'|'assistant','text':...}, ...] olarak döndür (2026-09-01,
        kullanıcı: Sohbet sekmesine "son mesaj"/"tüm session" iki seçenek). AYNI
        destekleniyor/desteklenmiyor sözleşmesi: None = bu CLI için yok, boş liste =
        destekleniyor ama henüz mesaj yok — sadece `last_exchange`'i override eden
        provider'ların override etmesi beklenir (varsayılan burada da None)."""
        return None

    def env_overrides(self, session_name: str) -> Dict[str, str]:
        """Bu CLI çağrısına ÖZEL env değişkenleri (varsayılan: yok).

        `spawn_session` bunları Popen'ın env dict'ine DEĞİL, komut satırının
        kendisine `env KEY=VAL ... <binary>` şeklinde gömer — çünkü tmux, ZATEN
        çalışan bir server'da yeni bir session açarken sadece kendi
        `update-environment` varsayılan listesindeki (DISPLAY, SSH_AUTH_SOCK, ...)
        değişkenleri yeni pane'e aktarır, Popen'a verilen env'in geri kalanını
        SESSİZCE YOK SAYAR — canlı doğrulandı (2026-08-27, agy COPS_NAME örneği).
        Komut satırına `env` ile gömmek tmux'un bu davranışını tamamen atlar.

        claude ismini zaten cmdline'a yazıyor (-n/--remote-control), env'e ihtiyacı
        yok. --remote-control muadili olmayan CLI'lar (agy) burada COPS_NAME döndürür.
        """
        return {}

    # ── discovery tarafı ─────────────────────────────────────────────────────

    @abstractmethod
    def matches_proc(self, cmd: List[str]) -> bool:
        """Ucuz ilk kapı: argv[0]'ın basename'i bu CLI'nın binary'si mi?"""

    @abstractmethod
    def extract_name(self, proc: "psutil.Process", cmd: List[str]) -> Optional[str]:
        """Bu proc'un session adı. None dönerse "bizim değil/isimlendirilemiyor"
        demektir — çağıran proc'u tamamen atlar (claude'da --remote-control yoksa)."""

    @abstractmethod
    def extract_info(self, cmd: List[str]) -> Dict[str, Optional[str]]:
        """{"sid":..., "model":..., "permission_mode":..., "effort":...} döndür."""

    # ── panel seçenekleri ────────────────────────────────────────────────────

    @abstractmethod
    def model_choices(self) -> List[str]:
        ...

    @abstractmethod
    def permission_modes(self) -> List[str]:
        ...

    @abstractmethod
    def effort_levels(self) -> List[str]:
        ...
