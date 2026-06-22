"""Fleet roster — models.tsv, roster.tsv ve suffix dosyalarını parse et."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional
from .paths import MODELS_TSV, ROSTER_TSV, SUFFIX_FILE


@dataclass
class RosterEntry:
    name: str    # taban isim (suffix'siz, ör. "hc")
    cwd: str
    model: str


def _parse_tsv(path: str) -> List[List[str]]:
    """TSV dosyasını satır listesi olarak döndür (boş + # satırları atla)."""
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                rows.append(line.split("\t"))
    except FileNotFoundError:
        pass
    return rows


def read_models() -> Dict[str, str]:
    """models.tsv → {base_name: model_id} (aktif girişler, # ile başlayanlar hariç)."""
    result = {}
    for row in _parse_tsv(MODELS_TSV):
        if len(row) >= 2:
            result[row[0]] = row[1]
    return result


def read_roster() -> List[RosterEntry]:
    """roster.tsv → [RosterEntry(name, cwd, model)]."""
    entries = []
    for row in _parse_tsv(ROSTER_TSV):
        if len(row) >= 3:
            entries.append(RosterEntry(name=row[0], cwd=row[1], model=row[2]))
        elif len(row) == 2:
            entries.append(RosterEntry(name=row[0], cwd=row[1], model=""))
    return entries


def read_suffix() -> Optional[int]:
    """suffix dosyasından mevcut nesil numarasını döndür (ör. 54)."""
    try:
        with open(SUFFIX_FILE, encoding="utf-8") as f:
            val = f.read().strip()
            return int(val) if val.isdigit() else None
    except FileNotFoundError:
        return None


def roster_by_name() -> Dict[str, RosterEntry]:
    """roster.tsv → {base_name: RosterEntry} — hızlı isim araması için."""
    return {e.name: e for e in read_roster()}
