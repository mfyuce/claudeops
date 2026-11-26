"""Kuru çalıştırma bayrağı (iş parçacığına özel). Açıkken komut kurulumu dosya yazmaz/silmez, durum değiştiren komut
koşturmaz, token üretmez, günlük tutmaz; dönen komut satırı gerçek koşununkidir. Yaprak modül (bağımlılığı yok)."""
import threading

_STATE = threading.local()


class preview_only:
    def __enter__(self):
        self._prev = active()
        _STATE.on = True

    def __exit__(self, *exc):
        _STATE.on = self._prev


def active() -> bool:
    return getattr(_STATE, "on", False)
