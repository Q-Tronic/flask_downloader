#!/usr/bin/env python3
"""Archiwizuje stare rootowe JSON-y po migracji do data/."""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path


LEGACY_TO_CURRENT = {
    "flask_downloader_config.json": Path("data/config.json"),
    "flask_downloader_jobs.json": Path("data/jobs.json"),
    "flask_downloader_users.json": Path("data/users.json"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Przenieś stare rootowe pliki JSON do katalogu backup po potwierdzonej migracji."
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Root projektu Flask Downloader. Domyślnie bieżący katalog.",
    )
    parser.add_argument(
        "--archive-dir",
        default="",
        help="Docelowy katalog archiwum. Domyślnie backups/legacy-data-YYYYmmdd-HHMMSS.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pokaż tylko co zostałoby zarchiwizowane, bez przenoszenia plików.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    archive_dir = (
        Path(args.archive_dir).resolve()
        if args.archive_dir
        else project_root / "backups" / f"legacy-data-{time.strftime('%Y%m%d-%H%M%S')}"
    )

    moved_any = False

    for legacy_name, current_rel_path in LEGACY_TO_CURRENT.items():
        legacy_path = project_root / legacy_name
        current_path = project_root / current_rel_path

        if not legacy_path.exists():
            print(f"[skip] {legacy_name}: brak starego pliku")
            continue
        if not current_path.exists():
            print(f"[skip] {legacy_name}: brak nowego odpowiednika {current_rel_path}")
            continue

        target_path = archive_dir / legacy_name
        print(f"[move] {legacy_path} -> {target_path}")
        if args.dry_run:
            moved_any = True
            continue

        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy_path), str(target_path))
        moved_any = True

    if not moved_any:
        print("Brak legacy JSON-ów do uporządkowania.")
        return 0

    if args.dry_run:
        print("Dry-run zakończony. Nic nie zostało przeniesione.")
    else:
        print(f"Zarchiwizowano stare rootowe JSON-y do: {archive_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
