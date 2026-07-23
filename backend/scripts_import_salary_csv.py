from __future__ import annotations

import argparse
from pathlib import Path

from services.slate_data import import_salary_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a DK or FD salary export into LineupLab")
    parser.add_argument("site", choices=("dk", "fd"))
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--date", dest="game_date")
    args = parser.parse_args()
    data = import_salary_csv(
        args.site,
        args.csv_file.read_text(encoding="utf-8-sig"),
        game_date=args.game_date,
        source=f"file:{args.csv_file.name}",
    )
    print(f"Imported {len(data['players'])} {args.site.upper()} players for {data['game_date']}")


if __name__ == "__main__":
    main()
