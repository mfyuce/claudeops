"""Instance kaydı: ~/.claude/claudeops/instances.json.

Blueprint = roster.tsv satırı. Instance = bir blueprint'ten (ya da diag'dan) açılan,
roster'a YAZILMAYAN session. "Çalışıyor mu" burada tutulmaz, hep canlı proc
taramasından türetilir. İsimler asla tekrar kullanılmaz (claude resume'u jsonl
customTitle'ına, remote-control bridge'i isme bağlı) — bu yüzden "Unut" kaydı
silmez, `forgotten` işaretiyle Geçmiş'ten gizler.
"""
from __future__ import annotations
import datetime
import fcntl
import json
import os
import re
import time
from contextlib import contextmanager
from typing import Callable, Dict, Optional

from .atomic_json import atomic_write_json
from .paths import CLAUDEOPS_DIR

INSTANCES_JSON = os.path.join(CLAUDEOPS_DIR, "instances.json")
_LOCK_PATH = INSTANCES_JSON + ".lock"
_VERSION = 1

# `_generate_new_chat_name`'in ürettiği şekil: <blueprint><YYYYMMDD>[_N...]
AUTO_NAME_RE = re.compile(r"^([a-z][a-z0-9]*?)(\d{8})((?:_\d+)*)$")
# Tarihten sonra elle ek almış türevler de (mtsyn20260909fablereview) bu şekle uyar.
DERIVED_NAME_RE = re.compile(r"^([a-z][a-z0-9]*?)(\d{8})([a-z0-9_]*)$")

DIAG_PREFIX = "diag"


class InstancesCorrupt(RuntimeError):
    pass


_cache_key: Optional[tuple] = None
_cache: Dict[str, dict] = {}


def read_strict() -> dict:
    """Eksikse boş şekil; bozuksa InstancesCorrupt (yazıcılar üstüne yazmasın diye)."""
    try:
        with open(INSTANCES_JSON, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"version": _VERSION, "instances": {}}
    except (json.JSONDecodeError, OSError) as e:
        raise InstancesCorrupt(f"{INSTANCES_JSON} okunamadı: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("instances"), dict):
        raise InstancesCorrupt(f"{INSTANCES_JSON} beklenen şekilde değil")
    return data


def load_instances() -> Dict[str, dict]:
    """{isim: kayıt}. Okuyucular için toleranslı: bozuk dosyada boş döner."""
    global _cache_key, _cache
    try:
        st = os.stat(INSTANCES_JSON)
    except FileNotFoundError:
        _cache_key, _cache = None, {}
        return {}
    key = (st.st_ino, st.st_mtime_ns, st.st_size)
    if key != _cache_key:
        try:
            _cache = read_strict()["instances"]
        except InstancesCorrupt:
            _cache = {}
        _cache_key = key
    return dict(_cache)


def get_instance(name: str) -> Optional[dict]:
    return load_instances().get(name)


@contextmanager
def _locked():
    os.makedirs(os.path.dirname(_LOCK_PATH), exist_ok=True)
    with open(_LOCK_PATH, "w") as fd:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)


def _mutate(fn: Callable[[Dict[str, dict]], object]) -> object:
    with _locked():
        data = read_strict()
        result = fn(data["instances"])
        data["version"] = _VERSION
        atomic_write_json(INSTANCES_JSON, data)
    return result


def record_instance(name: str, *, blueprint: Optional[str], cwd: str, cli: str, model: str,
                    permission_mode: str = "", effort: str = "", origin: str,
                    created_at: Optional[float] = None) -> None:
    """Upsert. Var olan kaydın created_at/origin'i korunur; launch parametreleri güncellenir."""
    now = time.time()

    def _apply(items: Dict[str, dict]) -> None:
        old = items.get(name) or {}
        items[name] = {
            "blueprint": blueprint,
            "cwd": cwd,
            "cli": cli,
            "model": model,
            "permission_mode": permission_mode,
            "effort": effort,
            "created_at": old.get("created_at") or created_at or now,
            "last_started_at": old.get("last_started_at"),
            "origin": old.get("origin") or origin,
        }

    _mutate(_apply)


def mark_started(name: str, *, cli: str, model: str, permission_mode: str, effort: str) -> None:
    """Bir sonraki "Devam ettir"in varsayılanları, son başlatmanın gerçek parametreleri olsun."""

    def _apply(items: Dict[str, dict]) -> None:
        rec = items.get(name)
        if rec is None:
            return
        rec.update(cli=cli, model=model, permission_mode=permission_mode, effort=effort,
                   last_started_at=time.time())
        rec.pop("forgotten", None)

    _mutate(_apply)


def add_missing(records: Dict[str, dict]) -> int:
    """Toplu içe aktarma (migrasyon): sadece OLMAYAN isimleri ekler, var olana dokunmaz."""

    def _apply(items: Dict[str, dict]) -> int:
        n = 0
        for name, rec in records.items():
            if name not in items:
                items[name] = dict(rec)
                n += 1
        return n

    return int(_mutate(_apply) or 0)


def forget_instance(name: str) -> bool:
    """Geçmiş'ten gizler ama kaydı SİLMEZ: isim rezerve kalmalı (bkz. modül docstring'i)."""

    def _apply(items: Dict[str, dict]) -> bool:
        rec = items.get(name)
        if rec is None or rec.get("forgotten"):
            return False
        rec["forgotten"] = True
        return True

    return bool(_mutate(_apply))


def rename_blueprint(old: str, new: str) -> int:
    def _apply(items: Dict[str, dict]) -> int:
        n = 0
        for rec in items.values():
            if rec.get("blueprint") == old:
                rec["blueprint"] = new
                n += 1
        return n

    return int(_mutate(_apply) or 0)


def _norm(path: str) -> str:
    return os.path.normpath(path) if path else ""


def infer_blueprint(name: str, cwd: str, blueprints: Dict[str, str]) -> Optional[str]:
    """`blueprints` = {ad: cwd}. Öncelik: önek+aynı cwd > aynı cwd'li TEK blueprint > önek."""
    m = DERIVED_NAME_RE.match(name)
    if not m:
        return None
    prefix = m.group(1)
    target = _norm(cwd)
    if prefix in blueprints and _norm(blueprints[prefix]) == target:
        return prefix
    same_cwd = [b for b, c in blueprints.items() if _norm(c) == target]
    if len(same_cwd) == 1:
        return same_cwd[0]
    if prefix in blueprints:
        return prefix
    return None


def created_at_from_name(name: str) -> Optional[float]:
    m = DERIVED_NAME_RE.match(name)
    if not m:
        return None
    try:
        return datetime.datetime.strptime(m.group(2), "%Y%m%d").timestamp()
    except ValueError:
        return None
