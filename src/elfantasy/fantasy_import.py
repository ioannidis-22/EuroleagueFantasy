"""Import the fantasy game's per-matchday export (players_stats.xlsx)."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd

from .store import replace_rows

EXPECTED_COLUMNS = [
    "ID", "Name", "Surname", "Active", "Position", "Team", "FPT", "Quotation", "Plus",
    "Pts", "Reb", "Ast", "Stl", "Tov", "Blk", "Blka", "Fd", "Pf", "Fg missed", "Ft missed",
    "Win 1-10", "Win 11-20", "Win 20", "Win ot", "Loss 1-10", "Loss 11-20", "Loss 20", "Loss ot",
]
RENAME = {
    "ID": "fantasy_id", "Name": "name", "Surname": "surname", "Position": "position", "Team": "team",
    "FPT": "fpt", "Quotation": "price", "Plus": "plus", "Pts": "pts", "Reb": "reb", "Ast": "ast",
    "Stl": "stl", "Tov": "tov", "Blk": "blk", "Blka": "blka", "Fd": "fd", "Pf": "pf",
    "Fg missed": "fg_missed", "Ft missed": "ft_missed", "Win 1-10": "win_1_10",
    "Win 11-20": "win_11_20", "Win 20": "win_20", "Win ot": "win_ot", "Loss 1-10": "loss_1_10",
    "Loss 11-20": "loss_11_20", "Loss 20": "loss_20", "Loss ot": "loss_ot",
}
PLAYER_COLS = ["fantasy_id", "name", "surname", "position", "team", "price", "plus", "fpt", "pts",
               "reb", "ast", "stl", "tov", "blk", "blka", "fd", "pf", "fg_missed", "ft_missed"]
COACH_COLS = ["name", "surname", "team", "price", "plus", "fpt", "win_1_10", "win_11_20", "win_20",
              "win_ot", "loss_1_10", "loss_11_20", "loss_20", "loss_ot"]
TEXT_COLS = {"name", "surname", "position", "team"}
FOOTER = re.compile(r"^\s*Reference matchdays:\s*(.*)$")


class ExportFormatError(ValueError):
    def __init__(self, missing: list[str], unexpected: list[str] | None = None):
        self.missing = missing
        self.unexpected = unexpected or []
        super().__init__(f"Export format changed. Missing: {missing}; unexpected: {self.unexpected}")


@dataclass
class FantasyExport:
    players: pd.DataFrame
    coaches: pd.DataFrame
    reference_matchdays: list[int]
    file_hash: str


def _num(v):
    if v is None or (isinstance(v, str) and v.strip() in ("", "-")):
        return np.nan
    return float(v)


def _fantasy_id(v) -> str:
    """IDs are opaque text: numeric ones may arrive as int/float, some are letters (e.g. 'TGB')."""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def parse_export(path: Path) -> FantasyExport:
    path = Path(path)
    data = path.read_bytes()
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    wb.close()
    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    header = [h for h in header if h]
    missing = [c for c in EXPECTED_COLUMNS if c not in header]
    unexpected = [c for c in header if c not in EXPECTED_COLUMNS]
    if missing or unexpected:
        raise ExportFormatError(missing, unexpected)

    matchdays: list[int] | None = None
    records = []
    for r in rows[1:]:
        first = r[0] if r else None
        if isinstance(first, str) and (m := FOOTER.match(first)):
            matchdays = [int(x) for x in re.findall(r"\d+", m.group(1))]
            continue
        if all(v is None for v in r):
            continue
        records.append(dict(zip(header, r)))
    if matchdays is None:
        raise ExportFormatError(["Reference matchdays footer"])

    df = pd.DataFrame(records).rename(columns=RENAME)
    for c in df.columns:
        if c in TEXT_COLS:
            df[c] = df[c].astype(str).str.strip()
        elif c not in ("Active", "fantasy_id"):
            df[c] = df[c].map(_num)
    is_coach = df["position"] == "Head Coach"
    players = df.loc[~is_coach, PLAYER_COLS].copy()
    players["fantasy_id"] = players["fantasy_id"].map(_fantasy_id)
    coaches = df.loc[is_coach, COACH_COLS].copy()
    return FantasyExport(players.reset_index(drop=True), coaches.reset_index(drop=True),
                         matchdays, hashlib.sha256(data).hexdigest())


def import_export(conn: sqlite3.Connection, path: Path) -> int:
    e = parse_export(path)
    md = max(e.reference_matchdays)
    snap = pd.DataFrame([{"matchday": md, "reference_matchdays": json.dumps(e.reference_matchdays),
                          "imported_at": datetime.now().isoformat(timespec="seconds"),
                          "file_hash": e.file_hash}])
    replace_rows(conn, "snapshots", snap, where={"matchday": md})
    replace_rows(conn, "fantasy_players", e.players.assign(matchday=md), where={"matchday": md})
    replace_rows(conn, "fantasy_coaches", e.coaches.assign(matchday=md), where={"matchday": md})
    return md
