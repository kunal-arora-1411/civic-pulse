"""Top up the evaluation candidates from Openverse (Flickr photos).

    uv run python scripts/eval/fetch_openverse.py --label streetlight --per-class 25
    uv run python scripts/eval/fetch_commons.py download --manifest scripts/eval/candidates.csv

Wikimedia Commons is the primary source (``fetch_commons.py``), but it
rate-limits media downloads that miss its caches, and an obscure set like
this one misses almost every time; after about a hundred files the limit
held for hours. Openverse (openverse.org) indexes openly licensed images
from many providers; this script asks it for Flickr photos only, so the
files come from Flickr's CDN. The licence rule is the same: CC0, the public
domain mark, CC BY and CC BY-SA, with creator, licence and photo page
recorded. Openverse allows anonymous clients 20 requests a minute and 200 a
day; a full run makes a few dozen.

Rows are appended to ``candidates.csv`` and reviewed and finalised exactly
like the Commons ones.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.eval.fetch_commons import CANDIDATES, USER_AGENT
from scripts.eval.manifest import LABELS, Item, is_open_license, read_manifest, write_manifest

API = "https://api.openverse.org/v1/images/"
API_INTERVAL = 3.5  # 20 a minute for anonymous clients
MIN_SHORT_SIDE = 400

QUERIES: dict[str, list[str]] = {
    "pothole": ["pothole india", "pothole road", "potholes street"],
    "waste": [
        "garbage street india",
        "garbage dump india",
        "rubbish pile street",
        "garbage pile",
        "trash dumped street",
        "fly tipping",
    ],
    "waterlogging": [
        "flooded street india",
        "waterlogged road",
        "mumbai rain flooded street",
        "flooded road cars",
        "street flooding rain",
        "monsoon flood street",
        "flooded street",
    ],
    "streetlight": [
        "street light india",
        "street lamp pole road",
        "streetlight night",
        "street light pole",
        "lamp post street",
        "broken street light",
        "street lamp",
    ],
    "drainage": [
        "open drain india",
        "sewer drain street india",
        "clogged drain garbage",
        "nala drain city",
        "open sewer india",
        "drainage canal garbage city",
        "street gutter drain",
        "storm drain",
        "sewer drain",
    ],
    "not_civic": [
        "indian food thali",
        "selfie",
        "living room interior",
        "office desk",
        "handwritten letter",
        "dog portrait",
        "classroom india",
    ],
}
LICENSES = {"cc0": "CC0", "pdm": "Public domain", "by": "CC BY", "by-sa": "CC BY-SA"}


def _licence_name(result: dict[str, Any]) -> str:
    base = LICENSES.get(result.get("license", ""), "")
    version = result.get("license_version") or ""
    if base in ("CC BY", "CC BY-SA") and version:
        return f"{base} {version}"
    return base


def search(
    label: str,
    per_class: int,
    per_query: int,
    known: set[str],
    queries: list[str] | None = None,
    pages: int = 1,
) -> list[Item]:
    client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60)
    found: list[Item] = []
    for query, page_no in [
        (q, p) for q in (queries or QUERIES[label]) for p in range(1, pages + 1)
    ]:
        if len(found) >= per_class:
            break
        time.sleep(API_INTERVAL)
        response = client.get(
            API,
            params={
                "q": query,
                "license": ",".join(LICENSES),
                "source": "flickr",
                "page_size": 20,
                "page": page_no,
                "mature": "false",
            },
        )
        if response.status_code == 429:
            print(f"  Openverse rate limit reached; stopping ({response.text[:120]})")
            break
        response.raise_for_status()
        taken = 0
        for result in json.loads(response.content).get("results", []):
            if taken >= per_query or len(found) >= per_class:
                break
            page = result.get("foreign_landing_url") or ""
            licence = _licence_name(result)
            width, height = result.get("width") or 0, result.get("height") or 0
            if not page or page in known or not is_open_license(licence):
                continue
            if width and height and min(width, height) < MIN_SHORT_SIDE:
                continue
            creator = " ".join(str(result.get("creator") or "Unknown author").split())[:200]
            found.append(
                Item(
                    path_or_url=result["url"],
                    label=label,
                    source=page,
                    license=licence,
                    attribution=f"{creator} / Flickr (via Openverse)",
                    license_url=result.get("license_url") or "",
                )
            )
            known.add(page)
            taken += 1
        print(f"  {label}: {len(found)} after {query!r} page {page_no}")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--label", action="append", choices=LABELS, required=True)
    parser.add_argument("--per-class", type=int, default=25)
    parser.add_argument("--per-query", type=int, default=10)
    parser.add_argument("--out", type=Path, default=CANDIDATES)
    parser.add_argument("--query", action="append", help="instead of the built-in queries")
    parser.add_argument("--pages", type=int, default=1, help="result pages per query")
    args = parser.parse_args(argv)
    previous = read_manifest(args.out) if args.out.is_file() else []
    known = {i.source for i in previous}
    added: list[Item] = []
    for label in args.label:
        added += search(
            label, args.per_class, args.per_query, known, queries=args.query, pages=args.pages
        )
    write_manifest(previous + added, args.out)
    print(f"added {len(added)} candidates to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
