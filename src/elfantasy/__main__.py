"""Command line: `python -m elfantasy refresh` / `python -m elfantasy import <xlsx>`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .el_client import ELClient
from .fantasy_import import ExportFormatError, import_export
from .paths import cache_dir, db_path, settings_path
from .refresh import refresh_season
from .settings import load_settings
from .store import connect


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="elfantasy")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh", help="download fixtures and new box scores")
    r.add_argument("--seasons", nargs="*")
    i = sub.add_parser("import", help="import a fantasy export (.xlsx)")
    i.add_argument("xlsx", type=Path)
    a = ap.parse_args(argv)

    s = load_settings(settings_path())
    conn = connect(db_path())
    if a.cmd == "import":
        try:
            md = import_export(conn, a.xlsx)
        except ExportFormatError as e:
            print(f"Import refused: {e}", file=sys.stderr)
            return 2
        print(f"Imported matchday {md}")
        return 0

    seasons = a.seasons or [*s.history_seasons, s.season]
    client = ELClient(cache_dir(), delay_s=s.api_delay_s)
    status = 0
    for season in seasons:
        rep = refresh_season(conn, client, season, source="live" if season == s.season else "v3",
                             progress=lambda k, n: print(f"\r{season}: {k}/{n}", end="", flush=True))
        print(f"\n{season}: {rep.games_total} games, {rep.new_box_scores} new box scores, "
              f"{len(rep.failed)} failed")
        for code, msg in rep.failed:
            print(f"  failed {code}: {msg}")
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
