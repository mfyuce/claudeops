"""CLI provider arayüzü — her yönetilen CLI (claude, agy, ...) bu sınıfı doldurur.

Manager kod (spawn.py/discovery.py/commands/web.py) YALNIZCA bu arayüz
üzerinden çağırır; hiçbir yerde `if cli == "agy"` dallanması OLMAMALI —
yeni bir CLI eklemek yeni bir provider dosyası + registry'ye bir satır demek.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

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

    def handover_model_downgrade(self, current_model: str) -> Optional[str]:
        """Handover'ın wrap-up mesajı gibi 'mekanik' bir iş için `current_model`
        yerine GEÇİCİ kullanılacak daha ucuz bir model adı — `current_model`
        zaten yeterince ucuzsa, tanınmıyorsa, ya da bu CLI için kavram
        tanımsızsa None (çağıran hiçbir model-değiştirme komutu göndermez).
        None = varsayılan (last_exchange/full_history/compact_command ile
        AYNI "yok=None" sözleşmesi) — sadece destekleyen provider override
        eder (2026-09-04, sadece claude)."""
        return None

    def apply_live_model_switch(self, tmux_name: str, target_model: str) -> None:
        """`tmux_name` CANLI session'ına model'i `target_model`'e değiştiren
        komutu (varsa) güvenli şekilde uygular — bir onay diyaloğu açılırsa
        onu da halleder. Varsayılan no-op (bu CLI canlı model değişimini
        desteklemiyor/tanımsız, `handover_model_downgrade()` zaten None
        döndüğü için pratikte hiç çağrılmaz)."""
        return

    def compact_command(self) -> Optional[str]:
        """Bu CLI'nın konuşma-özetleme slash-command'ı (ör. `/compact`), varsa.
        None (varsayılan) = bu CLI için böyle bir kavram yok — panelin "compact"
        aksiyonu bu session'ı desteklenmiyor sayıp reddeder. `last_exchange`/
        `full_history` ile AYNI sözleşme (None = yok, sadece destekleyen provider
        override eder) — `_compact()`'in ESKİDEN yaptığı `if cli != "claude"`
        string-karşılaştırması (2026-09-04, provider-audit) bunun yerine geçti,
        çünkü o hardcode CliProvider'ın "yeni CLI = yeni provider dosyası,
        manager kodunda dallanma YOK" kuralını ihlal ediyordu. Sadece GATE'i
        polimorfik yapar — headless çağrının kendisi (`argv`/binary şekli) hâlâ
        claude'a özgü kalıyor (`_compact()`), başka bir provider gerçekten
        compact kazanırsa O ZAMAN genellenir; bugün var olmayan bir ikinci
        veri noktasına göre spekülatif olarak genellemek yok."""
        return None

    def extra_file_roots(self, cwd: str) -> List[Tuple[str, str]]:
        """Panelin dosya-gezgini için bu CLI'ya özgü EK kök dizin(ler) —
        [(key, absolute-path), ...]. Varsayılan (boş liste) = sadece proje
        klasörünün kendisi taranabilir (o zaten `files.py`'de ayrıca ekleniyor,
        burada YOK). Sadece kendi transkriptini per-cwd bir klasörde tutan
        provider'lar override eder (2026-09-05, sadece claude — `~/.claude/
        projects/<encoded-cwd>/`; agy/codex'in claude'unki gibi TEK
        başına-per-cwd bir meta-dizini yok — agy conversation-id'leri global bir
        cache'te, codex rollout'ları tarih-bazlı global bir arşivde, ikisi de
        BU cwd'ye özel bir KLASÖR değil). `last_exchange`/`full_history` ile
        AYNI "yok=boş/None" mimari deseni. Döndürülen yollar var olmayabilir
        (caller `os.path.isdir` ile filtreler) — burada dosya sistemine
        dokunmadan sadece ADAY yol(lar)ı hesapla."""
        return []

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
