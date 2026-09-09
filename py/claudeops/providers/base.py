"""CLI provider arayüzü — her yönetilen CLI (claude, agy, ...) bu sınıfı doldurur.

Manager kod (spawn.py/discovery.py/commands/web.py) YALNIZCA bu arayüz
üzerinden çağırır; hiçbir yerde `if cli == "agy"` dallanması OLMAMALI —
yeni bir CLI eklemek yeni bir provider dosyası + registry'ye bir satır demek.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, FrozenSet, List, Optional, Tuple

import psutil


class CliProvider(ABC):
    name: str  # "claude" | "agy" | ...

    # ── spawn tarafı ─────────────────────────────────────────────────────────

    @abstractmethod
    def resolve_resume_id(self, cwd: str, in_use: FrozenSet[str] = frozenset(),
                          session_name: str = "") -> Optional[str]:
        """cwd için devam edilecek konuşma/sid'i bul (yoksa None → fresh/new).

        `in_use`: ŞU AN başka canlı session'ları TANIMLAYAN dizeler — hem
        resume-id'leri hem ADLARI (ikisi bir arada: bir konuşmanın "sahibi"
        provider'a göre ya id'siyle ya adıyla belli oluyor — claude'un jsonl'ı
        `-n NAME`'i `customTitle` olarak yazıyor, bir `--new` session'ın sid'i ise
        komut satırında HİÇ görünmüyor). Bu kümedeki hiçbir şey ASLA
        döndürülmemeli. Aynı cwd'yi paylaşan iki session (farklı isim, aynı klasör
        ya da aynı proje kökü) yoksa bu küme boştur; varsa, ikisinin AYNI konuşmayı
        resume etmesi = tek bir jsonl'a iki process'in birden yazması = konuşma
        truncation riski (2026-09-07 canlı yuhem vakası: `yuhem-agent` ile
        `ancient-script-pipeline-fd` ikisi de `resume:e2692367` döndü).

        `session_name`: hedef session'ın adı — provider'ın transcript'inde bir isim/
        başlık varsa (claude'un jsonl'ındaki `customTitle`) AYNI isimli konuşma
        TERCİH edilir. Sadece tercih: isim eşleşmesi bulunamazsa (ör. session yeniden
        adlandırılmış) en yeni uygun konuşmaya düşülür — yeniden-adlandırma
        geçmişi koparmasın."""

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

    def input_settle_delay(self) -> float:
        """`tmux_send_keys()`'in literal-metin gönderiminden SONRA, Enter
        göndermeden ÖNCE beklemesi gereken saniye. Varsayılan 0.0 (gerek yok) —
        `last_exchange`/`compact_command` ile AYNI "yok=no-op, sadece kanıtlanmış
        ihtiyacı olan provider override eder" sözleşmesi. claude zaten anlık
        Enter'ı doğru işliyor (1200+ karakterli çok-satırlı/Türkçe-karakterli
        handover wrap-up mesajıyla bile canlı doğrulanmıştı, bkz. handover.py'nin
        modül docstring'i) — yeni bir gecikme ona hiçbir fayda sağlamaz, sadece
        kanıtlanan ihtiyacı olana uygulanıyor (2026-09-05, codex — bkz.
        `CodexProvider.input_settle_delay`)."""
        return 0.0

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

    def mode_status_patterns(self) -> Dict[str, str]:
        """{mod: regex} — bu CLI'ın durum çubuğunda AKTİF izin modunu ele veren
        metinler. Boş dict (VARSAYILAN) = bu CLI'da canlı mod OKUMA yok; panel
        mod göstermez/seçtirmez. `last_exchange`/`compact_command` ile aynı
        "yok = boş/None" sözleşmesi — `if cli == ...` dallanması YOK."""
        return {}

    def busy_status_pattern(self) -> Optional[str]:
        """Durum çubuğunda session bir turu İŞLERKEN (thinking/tool-çalışırken)
        görünen, idle'da KAYBOLAN metin — panelin "gerçekten iş yapıyor mu"
        göstergesi (`web.py`'nin `_is_busy_cached`'i). None (VARSAYILAN) = bu
        CLI'da böyle bir sinyal yok/doğrulanmadı → panel busy alanını None
        (bilinmiyor) bırakır, False'la KARIŞTIRMAZ. Mod metinleri gibi ANSI'yi
        KORUYAN `-e` capture'a karşı eşleştirilir — çağıran taraf `strip_ansi`
        uygulamalı (bkz. `tmux_backend.strip_ansi`)."""
        return None

    def cyclable_modes(self) -> List[str]:
        """Shift+Tab (BTab) döngüsüyle CANLIYKEN ulaşılabilen modlar, döngüde
        göründükleri sırayla; İLK eleman "durum çubuğunda hiçbir işaret yoksa
        geçerli olan" moddur. Boş liste (VARSAYILAN) = bu CLI'da canlı mod
        DEĞİŞTİRME yok → `_term_set_mode` kör kör BTab basmaz, panel de mod
        seçicisini hiç göstermez. `permission_modes()`'tan AYRI ve daha dar:
        o, session BAŞLATIRKEN verilebilecek tüm modlar."""
        return []

    def snapshot_for_live_sid(self, cwd: str) -> object:
        """`resolve_resume_id()`/`last_exchange(cwd, sid=None)` bir konuşmayı
        SADECE provider'ın kendi cache/index'i (varsa) onu zaten biliyorsa
        bulabilir. agy'de bu `~/.gemini/antigravity-cli/cache/
        last_conversations.json` — ve CANLI DOĞRULANDI (2026-09-09): bu dosya
        session HENÜZ ÇIKMADAN/ÖLDÜRÜLMEDEN asla güncellenmiyor. Yani ilk kez
        (hiç `--conversation`'la resume edilmemiş) çalışan bir agy session'ının
        konuşması, session öldürülene kadar bu yoldan HİÇBİR ZAMAN okunamıyor —
        `/v1/chat/completions`'ta (TOBEDECIDED#21) bu tam olarak fresh bir agy
        session'a gönderilen mesajın sessizce 504 timeout'a düşmesine yol açan
        şey.

        Bu metod, çağırana (o katman gibi) mesajı GÖNDERMEDEN ÖNCE ucuz bir
        "durum" yakalama imkanı verir — dönen değer OPAQUE, sadece aşağıdaki
        `discover_live_sid()`'e geri verilmek için. None (VARSAYILAN) = bu
        provider'da cache-BAĞIMSIZ bir canlı-keşif yolu yok/gerekmiyor
        (claude/codex kendi sid'lerini zaten cmdline'dan ya da jsonl/rollout
        dosyasından anında okuyabiliyor — agy'nin bu belirli açığı onlarda
        yok, `resolve_resume_id`/`last_exchange` zaten çalışıyor)."""
        return None

    def discover_live_sid(self, cwd: str, snapshot: object) -> Optional[str]:
        """`snapshot`'ın (yukarıdaki `snapshot_for_live_sid()`'in döndürdüğü)
        YAKALANDIĞI andan SONRA ortaya çıkan bir konuşma id'si var mı? Varsa
        onu döndür — çağıran bunu doğrudan `last_exchange`/`full_history`'ye
        `sid` olarak geçirebilir, `resolve_resume_id()`'e/cache'e HİÇ
        dokunmadan (2026-09-09 canlı doğrulandı: agy'nin gerçek `.db` dosyası
        gönderimden ~2s sonra oluşuyor ve `steps` tablosu turn ilerlerken
        GERÇEK ZAMANLI yazılıyor — assistant satırı ekrandaki yanıt
        tamamlanmadan ÖNCE bile okunabiliyordu).

        None = ya henüz yok (çağıran tekrar poll'lamalı, timeout'a kadar) ya
        da provider `snapshot_for_live_sid()`'de zaten None döndürdüğü için
        hiç desteklenmiyor — ikisi çağıran için AYNI davranışı gerektirir
        (bekle/timeout), o yüzden tek bir None sözleşmesi yeterli."""
        return None
