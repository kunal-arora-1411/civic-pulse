"""Contact sheets for hand-checking a manifest's labels.

    uv run python scripts/eval/review_sheet.py --manifest scripts/eval/candidates.csv

Writes one numbered grid per label (``<out>/<label>-<n>.jpg``) plus an
index CSV mapping each number to the image's source page, so rejects can
be copied into ``rejected.csv`` with a reason. Images not downloaded yet
and ones already rejected are left out.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.eval.manifest import (
    DEFAULT_CACHE,
    DEFAULT_MANIFEST,
    LABELS,
    cache_path,
    load_image,
    read_manifest,
)

CELL = 220
COLUMNS = 6
ROWS = 5


def _rejected(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["source"] for row in csv.DictReader(handle)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--out", type=Path, default=DEFAULT_CACHE / "review")
    args = parser.parse_args(argv)
    parser_items = read_manifest(args.manifest)
    # Only what has been downloaded; numbers refer to this filtered list.
    items = [i for i in parser_items if not i.is_remote or cache_path(i, args.cache).is_file()]
    rejected = _rejected(args.manifest.parent / "rejected.csv")
    items = [i for i in items if i.source not in rejected]
    args.out.mkdir(parents=True, exist_ok=True)
    index_rows = []
    for label in LABELS:
        group = [i for i in items if i.label == label]
        per_sheet = COLUMNS * ROWS
        for sheet_no, start in enumerate(range(0, len(group), per_sheet), 1):
            sheet = Image.new("RGB", (COLUMNS * CELL, ROWS * CELL), "white")
            draw = ImageDraw.Draw(sheet)
            for offset, item in enumerate(group[start : start + per_sheet]):
                number = start + offset
                try:
                    thumb = load_image(item, args.manifest.parent, args.cache)
                except FileNotFoundError:
                    continue
                thumb.thumbnail((CELL - 6, CELL - 22))
                x, y = (offset % COLUMNS) * CELL, (offset // COLUMNS) * CELL
                sheet.paste(thumb, (x + 3, y + 20))
                draw.rectangle((x, y, x + 44, y + 18), fill="black")
                draw.text((x + 4, y + 3), f"{number:03d}", fill="yellow")
                index_rows.append({"label": label, "number": number, "source": item.source})
            sheet.save(args.out / f"{label}-{sheet_no}.jpg", quality=85)
    with (args.out / "index.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["label", "number", "source"])
        writer.writeheader()
        writer.writerows(index_rows)
    print(f"contact sheets in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
