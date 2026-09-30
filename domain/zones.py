"""The zone table (docs/contact-engine/03-time-zone.md §4.1): NANPA's area-code file,
read as published, with two hand additions and its overlay groups. Anything it cannot
read fails the import."""

import csv
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path(__file__).parent / "data" / "npa_report.csv"

NY = "America/New_York"
CHI = "America/Chicago"
DEN = "America/Denver"
PHX = "America/Phoenix"
LA = "America/Los_Angeles"
ANC = "America/Anchorage"
ADAK = "America/Adak"
HNL = "Pacific/Honolulu"
PR = "America/Puerto_Rico"
GUAM = "Pacific/Guam"
PAGO = "Pacific/Pago_Pago"

ZONES = frozenset({NY, CHI, DEN, PHX, LA, ANC, ADAK, HNL, PR, GUAM, PAGO})

_VALUES = {
    "E": {NY}, "C": {CHI}, "M": {DEN}, "P": {LA},
    "EC": {NY, CHI}, "CM": {CHI, DEN}, "MP": {DEN, LA},
    "PT/MT only for W Wendover": {LA, DEN},
    "A": {PR}, "AK": {ANC}, "(UTC-10)": {HNL}, "(UTC+10)": {GUAM}, "UTC-11": {PAGO},
}
# Official clocks NANPA's letters miss; each only adds.
_HAND = {"928": {DEN}, "907": {ADAK}}
_POSTAL = {"CNMI": "MP"}


@dataclass(frozen=True)
class ZoneTable:
    by_code: dict[str, frozenset[str]]
    by_state: dict[str, frozenset[str]]

    @property
    def codes(self) -> frozenset[str]:
        return frozenset(self.by_code)

    def area(self, code: str) -> frozenset[str]:
        return self.by_code.get(code, frozenset())

    def state(self, state: str) -> frozenset[str]:
        return self.by_state.get(state, frozenset())


def _zones(npa: str, location: str, value: str) -> set[str]:
    if value not in _VALUES:
        raise ValueError(f"npa {npa}: unknown TIME_ZONE {value!r}")
    if location == "AZ":
        if value != "M":
            raise ValueError(f"npa {npa}: Arizona row is {value!r}, not 'M'")
        return {PHX}
    return set(_VALUES[value])


def load(path: Path) -> ZoneTable:
    with open(path, newline="") as f:
        first = f.readline()
        if not first.startswith("File Date"):
            raise ValueError(f"{path}: first line is not 'File Date': {first!r}")
        rows = [
            r for r in csv.DictReader(f)
            if r["COUNTRY"] == "US" and r["USE"] == "G" and r["IN_SERVICE"] == "Y"
        ]

    zones: dict[str, set[str]] = {}
    state_of: dict[str, str] = {}
    for r in rows:
        npa, location = r["NPA_ID"], r["LOCATION"]
        if npa in zones:
            raise ValueError(f"npa {npa} repeats")
        if location not in _POSTAL and not re.fullmatch(r"[A-Z]{2}", location):
            raise ValueError(f"npa {npa}: bad LOCATION {location!r}")
        zones[npa] = _zones(npa, location, r["TIME_ZONE"])
        state_of[npa] = _POSTAL.get(location, location)

    for npa, extra in _HAND.items():
        if npa not in zones:
            raise ValueError(f"hand-addition npa {npa} is not in the file")
        zones[npa] |= extra

    parent = {npa: npa for npa in zones}

    def root(npa: str) -> str:
        while parent[npa] != npa:
            npa = parent[npa]
        return npa

    for r in rows:
        members = [r["NPA_ID"]] + [
            m for m in re.findall(r"\d{3}", r["OVERLAY_COMPLEX"]) if m in zones
        ]
        for m in members[1:]:
            parent[root(m)] = root(members[0])

    group: dict[str, set[str]] = {}
    for npa, z in zones.items():
        group.setdefault(root(npa), set()).update(z)
    by_code = {npa: frozenset(group[root(npa)]) for npa in zones}

    by_state: dict[str, set[str]] = {}
    for npa, z in by_code.items():
        by_state.setdefault(state_of[npa], set()).update(z)

    return ZoneTable(
        by_code=by_code,
        by_state={s: frozenset(z) for s, z in by_state.items()},
    )


TABLE = load(DEFAULT_PATH)
