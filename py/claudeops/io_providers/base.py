"""IoProvider arayüzü — `providers/base.py`'nin `CliProvider`'ı DAR bir
muadili, tmux'suz/salt-IO backend'ler için (2026-09-23, TOBEDECIDED#44'ün
devamı: "shell/tmux olmadan provider ekleme yöntemimiz olmalı").

`CliProvider` "uzun ömürlü, etkileşimli bir tmux pane'i" varsayımı üzerine
kurulu (spawn_session/discovery/busy_status_pattern/handover...) — bu
arayüz o varsayımların HİÇBİRİNİ taşımıyor, sadece `CliProvider`'ın zaten
kanıtlanmış "proje (cwd) + isimli session + geçmişe bakıp devam et" kimliğini
(bkz. `resolve_resume_id`/`full_history`) tmux'suz haliyle tekrarlıyor: tek-
seferlik senkron soru-cevap + o projedeki session'ları listeleme + birinin
geçmişini okuma. Manager kod (web.py) SADECE registry (`io_providers/
__init__.py`) üzerinden çağırır — `if provider == "ucli"` dallanması YOK,
yeni bir tmux'suz backend eklemek = yeni bir provider dosyası + registry'ye
bir satır (aynı [[feedback-multi-backend-provider-pattern]] felsefesi)."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional


class IoProviderError(RuntimeError):
    """Bu katmanın tek hata sözleşmesi — her provider kendi alt-seviye
    istisnasını (ör. ucli_client.UcliError) bunun İÇİNE sarıp fırlatır, web.py
    hiçbir provider'a özel exception type'ı BİLMEZ/import ETMEZ."""


@dataclass
class FormField:
    """UI'nin bu provider için OTOMATİK form çizmesi için tek bir alan —
    `prompt`/`cwd`/`session` burada YOK (genel katman zaten sağlıyor),
    sadece provider'a özel olanlar (ör. ucli için model/endpoint/api_key)."""
    key: str
    label: str
    type: str = "text"  # "text" | "password"
    placeholder: str = ""
    required: bool = False


class IoProvider(ABC):
    name: str  # "ucli" | ...

    @abstractmethod
    def ask(self, cwd: str, session: str, prompt: str, fields: Dict[str, str]) -> dict:
        """Senkron tek-seferlik soru-cevap. `fields` bu provider'ın
        `form_fields()`'ının anahtarlarıyla eşleşir (fazlası yok sayılır,
        eksik zorunlu alan provider'ın kendi hata mesajıyla `IoProviderError`
        fırlatır). `session` boş string = provider'a göre değişen "durumsuz"
        anlamı (ucli'de: dosya I/O yok, her çağrı tamamen bağımsız)."""

    @abstractmethod
    def list_sessions(self, cwd: str) -> List[str]:
        """`cwd`'de var olan session isimleri, EN SON KULLANILANA göre sıralı
        (en yeni ilk — "devam et" listesinde en olası aday en üstte). Boş
        liste = hiç session yok, hata değil."""

    @abstractmethod
    def history(self, cwd: str, session: str) -> Optional[List[Dict[str, str]]]:
        """`session`ın geçmiş turları `[{"role": "user"|"assistant", "text":
        ...}, ...]` eskiden yeniye — `CliProvider.full_history` ile AYNI
        sözleşme. Session hiç yoksa boş liste (henüz soru sorulmamış demek,
        hata değil); dosya bozuksa/okunamıyorsa None (gerçek hata)."""

    @abstractmethod
    def form_fields(self) -> List[FormField]:
        ...
