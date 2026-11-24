"""Build and fetch the evaluation set from Wikimedia Commons.

    # 1. find candidates (Commons API; open licences only) -> candidates.csv
    uv run python scripts/eval/fetch_commons.py search
    # (optional) top up thin classes from Flickr via Openverse
    uv run python scripts/eval/fetch_openverse.py --label drainage
    # 2. download them into the cache, then look at them
    uv run python scripts/eval/fetch_commons.py download --manifest scripts/eval/candidates.csv
    uv run python scripts/eval/review_sheet.py --manifest scripts/eval/candidates.csv
    # 3. list the bad ones in rejected.csv (with a reason, or a relabel),
    #    then write the final manifest: rejects, near-duplicates and the
    #    per-class cap applied, split fixed
    uv run python scripts/eval/fetch_commons.py finalize
    # anyone else: fetch the images the committed manifest lists
    uv run python scripts/eval/fetch_commons.py download

Only CC0, public-domain, CC BY and CC BY-SA files are kept, with author,
licence and file page recorded for attribution. Requests are sequential
and spaced out, carry a descriptive User-Agent without personal details
and honour Retry-After. Images under 5 MB are fetched as the original
file, larger ones as the 500 px thumbnail (a standard Commons size).

Be patient with Commons. Files that aren't in its edge caches, which is
nearly all of a set like this, count against a small per-client budget;
after about a hundred quick downloads it answered 429 for hours, which is
why the committed set leans on Openverse for most classes. One file every
20 seconds (the default) stays within it.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import re
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.ai.phash import perceptual_hash
from scripts.eval.manifest import (
    DEFAULT_CACHE,
    DEFAULT_MANIFEST,
    EVAL_DIR,
    LABELS,
    Item,
    assign_splits,
    cache_path,
    is_open_license,
    load_image,
    read_manifest,
    write_manifest,
)

API = "https://commons.wikimedia.org/w/api.php"
# No HTTP library token: CDNs treat "python-httpx" and friends as bot traffic
# (Flickr's answers 502), and Wikimedia's UA policy asks for a descriptive name.
USER_AGENT = (
    "CivicPulse-eval-fetch/0.1 (open-source civic issue reporting; small evaluation "
    "set of openly licensed images)"
)
THUMB_WIDTH = 500
API_INTERVAL = 1.5  # seconds between API calls
# Files that aren't in Wikimedia's edge caches (most of an obscure set like
# this) count against a per-client budget, and exceeding it earns 429s with
# Retry-After of up to ten minutes that keep coming while you retry. One file
# every 20 seconds is slow but stays within it.
DOWNLOAD_INTERVAL = 20.0
OTHER_DOWNLOAD_INTERVAL = 3.0  # Flickr's CDN, for the Openverse top-up
CANDIDATES = EVAL_DIR / "candidates.csv"
REJECTED = EVAL_DIR / "rejected.csv"
MIN_SHORT_SIDE = 400
MAX_ORIGINAL_BYTES = 5_000_000

# Search queries per label, best first. Indian street scenes come first;
# generic ones top the class up. "filetype:bitmap" drops SVGs and PDFs.
QUERIES: dict[str, list[str]] = {
    "pothole": [
        'incategory:"Potholes in India"',
        "pothole road India filetype:bitmap",
        "potholes Bangalore filetype:bitmap",
        "potholes Mumbai filetype:bitmap",
        "pothole street filetype:bitmap",
        'deepcat:"Potholes by country" filetype:bitmap',
        "potholed road filetype:bitmap",
        "pothole Kerala road filetype:bitmap",
        "pothole Delhi road filetype:bitmap",
        "damaged road potholes India filetype:bitmap",
        "pothole puddle road filetype:bitmap",
        "pothole asphalt filetype:bitmap",
        "road pothole closeup filetype:bitmap",
    ],
    "waste": [
        "garbage street India filetype:bitmap",
        "garbage dump roadside India filetype:bitmap",
        'deepcat:"Litter in India" filetype:bitmap',
        "garbage heap road filetype:bitmap",
        "rubbish dumped street filetype:bitmap",
        "litter pile roadside filetype:bitmap",
        "garbage pile India city filetype:bitmap",
        "plastic waste street filetype:bitmap",
        "overflowing garbage bin street filetype:bitmap",
        "illegal dumping waste filetype:bitmap",
        "garbage Delhi street filetype:bitmap",
        "solid waste roadside Kerala filetype:bitmap",
    ],
    "waterlogging": [
        "waterlogging road India filetype:bitmap",
        "waterlogged street filetype:bitmap",
        "flooded street Mumbai filetype:bitmap",
        "flooded road India monsoon filetype:bitmap",
        "flooded street rain filetype:bitmap",
        "street flooding filetype:bitmap",
        "flooded street Chennai filetype:bitmap",
        "waterlogged road Kolkata filetype:bitmap",
        "rainwater flooded road vehicles filetype:bitmap",
    ],
    "streetlight": [
        'deepcat:"Street lights in India" filetype:bitmap',
        "street light pole India filetype:bitmap",
        "street lamp road India filetype:bitmap",
        "broken street light filetype:bitmap",
        "street light night road filetype:bitmap",
    ],
    "drainage": [
        "open drain India filetype:bitmap",
        "sewage drain street India filetype:bitmap",
        "clogged drain garbage filetype:bitmap",
        "nala Mumbai drain filetype:bitmap",
        "roadside drain filetype:bitmap",
        "open sewer street filetype:bitmap",
        "storm drain blocked filetype:bitmap",
        "manhole road India filetype:bitmap",
        "drainage channel garbage city filetype:bitmap",
        "sewer overflow street filetype:bitmap",
        "gutter blocked rubbish filetype:bitmap",
    ],
    "not_civic": [
        "Indian thali food filetype:bitmap",
        "selfie filetype:bitmap",
        "portrait woman India smiling filetype:bitmap",
        "living room interior filetype:bitmap",
        "office interior desk filetype:bitmap",
        "handwritten letter document filetype:bitmap",
        "screenshot software filetype:bitmap",
        "pet dog portrait filetype:bitmap",
        "classroom students India filetype:bitmap",
        "kitchen interior India filetype:bitmap",
    ],
}
# Titles with these words are drawings, maps or charts, not photographs.
_NOT_A_PHOTO = re.compile(
    r"\b(map|diagram|chart|logo|icon|plan|sketch|drawing|painting|poster|illustration|"
    r"stamp|graph|banner|flag)\b",
    re.IGNORECASE,
)
_TAGS = re.compile(r"<[^>]+>")


@dataclass
class Candidate:
    title: str
    label: str
    query: str
    thumb_url: str
    page_url: str
    license: str
    license_url: str
    attribution: str


class Commons:
    """A deliberately slow, sequential client for the Commons API."""

    def __init__(self, wikimedia_interval: float = DOWNLOAD_INTERVAL) -> None:
        self._client = self._new_client()
        self._last: dict[str, float] = {}
        self._wikimedia_interval = wikimedia_interval

    @staticmethod
    def _new_client() -> httpx.Client:
        return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True)

    def _wait(self, kind: str, interval: float) -> None:
        elapsed = time.monotonic() - self._last.get(kind, 0.0)
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self._last[kind] = time.monotonic()

    def _get(self, url: str, params: dict[str, Any] | None, kind: str, interval: float) -> bytes:
        for attempt in range(8):
            self._wait(kind, interval)
            response = self._client.get(url, params=params)
            if response.status_code in (429, 503) or (
                params and b'"code":"maxlag"' in response.content[:200]
            ):
                # Wait longer than asked: retrying the moment a penalty ends
                # tends to earn the next one.
                asked = float(response.headers.get("Retry-After") or 0)
                delay = max(asked * 1.5, 5 * 2**attempt)
                print(f"    throttled ({response.status_code}); waiting {delay:.0f}s")
                time.sleep(min(delay, 1200))
                # Start over on a fresh connection; a kept-alive one seemed
                # to stay throttled after the penalty had expired.
                self._client.close()
                self._client = self._new_client()
                continue
            response.raise_for_status()
            return response.content
        raise RuntimeError(f"gave up on {url} after repeated throttling")

    def api(self, **params: Any) -> dict[str, Any]:
        import json

        params = {"action": "query", "format": "json", "formatversion": 2, "maxlag": 5, **params}
        return json.loads(self._get(API, params, "api", API_INTERVAL))

    def download(self, url: str) -> bytes:
        if is_wikimedia(url):
            return self._get(url, None, "wikimedia", self._wikimedia_interval)
        return self._get(url, None, "other", OTHER_DOWNLOAD_INTERVAL)

    def search(self, query: str, limit: int = 50) -> list[str]:
        data = self.api(list="search", srsearch=query, srnamespace=6, srlimit=limit)
        return [hit["title"] for hit in data.get("query", {}).get("search", [])]

    def image_info(self, titles: list[str]) -> Iterator[dict[str, Any]]:
        for start in range(0, len(titles), 50):
            data = self.api(
                titles="|".join(titles[start : start + 50]),
                prop="imageinfo",
                iiprop="url|size|mime|extmetadata",
                iiurlwidth=THUMB_WIDTH,
                iiextmetadatafilter="LicenseShortName|LicenseUrl|Artist|Credit|Restrictions",
            )
            yield from data.get("query", {}).get("pages", [])


def is_wikimedia(url: str) -> bool:
    return url.startswith(("https://upload.wikimedia.org/", "https://thumb.wikimedia.org/"))


def _image_url(info: dict[str, Any]) -> str:
    """The original when it is small, else the 500 px thumbnail.

    Originals are static files: no rendering, no thumbnail rate limit, and
    their bytes never change, so the recorded sha256 stays valid.
    Thumbnails are re-rendered from time to time and rate-limited, but keep
    multi-megabyte originals off the wire. Commons appends utm_* tracking
    parameters to both; the bare URL is the stable one.
    """
    if info.get("size", 0) <= MAX_ORIGINAL_BYTES:
        return info["url"].split("?")[0]
    return (info.get("thumburl") or info["url"]).split("?")[0]


def _plain(value: str) -> str:
    return " ".join(html.unescape(_TAGS.sub(" ", value)).split())


def _rejected_titles() -> set[str]:
    if not REJECTED.is_file():
        return set()
    with REJECTED.open(encoding="utf-8", newline="") as handle:
        return {row["source"] for row in csv.DictReader(handle)}


def _to_candidate(page: dict[str, Any], label: str, query: str) -> Candidate | str:
    """A candidate, or the reason the file was skipped."""
    title = page.get("title", "")
    infos = page.get("imageinfo") or []
    if not infos:
        return "no image info"
    info = infos[0]
    meta = {k: v.get("value", "") for k, v in (info.get("extmetadata") or {}).items()}
    if info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
        return f"mime {info.get('mime')}"
    if min(info.get("width", 0), info.get("height", 0)) < MIN_SHORT_SIDE:
        return "too small"
    if _NOT_A_PHOTO.search(title):
        return "title suggests a drawing, map or chart"
    licence = _plain(meta.get("LicenseShortName", ""))
    if not is_open_license(licence):
        return f"licence {licence or 'unknown'}"
    if meta.get("Restrictions"):
        return f"restrictions {meta['Restrictions']}"
    artist = _plain(meta.get("Artist", "")) or _plain(meta.get("Credit", "")) or "Unknown author"
    return Candidate(
        title=title,
        label=label,
        query=query,
        thumb_url=_image_url(info),
        page_url=info.get("descriptionurl", ""),
        license=licence,
        license_url=meta.get("LicenseUrl", ""),
        attribution=f"{artist[:200]} / Wikimedia Commons",
    )


def search(
    per_class: int, per_query: int, labels: tuple[str, ...], known: set[str]
) -> list[Candidate]:
    commons = Commons()
    rejected = _rejected_titles()
    seen: set[str] = set(known)
    chosen: list[Candidate] = []
    for label in labels:
        found: list[Candidate] = []
        skipped: dict[str, int] = {}
        # A cap per query keeps one prolific search (or one photographer's
        # upload batch) from making up most of a class.
        cap = per_query if label != "not_civic" else max(4, per_query // 2)
        for query in QUERIES[label]:
            if len(found) >= per_class:
                break
            titles = [t for t in commons.search(query) if t not in seen]
            from_query = 0
            for page in commons.image_info(titles):
                if from_query >= cap:
                    break
                result = _to_candidate(page, label, query)
                if isinstance(result, str):
                    skipped[result.split(" ")[0]] = skipped.get(result.split(" ")[0], 0) + 1
                    continue
                if result.page_url in rejected or result.page_url in seen or result.title in seen:
                    continue
                seen.add(result.title)
                found.append(result)
                from_query += 1
                if len(found) >= per_class:
                    break
            print(f"  {label}: {len(found)} after {query!r}")
        print(f"{label}: {len(found)} candidates; skipped {skipped}")
        chosen.extend(found)
    return chosen


def download(
    items: list[Item],
    cache_dir: Path,
    *,
    skip_wikimedia: bool = False,
    labels: tuple[str, ...] = LABELS,
    interval: float = DOWNLOAD_INTERVAL,
) -> list[Item]:
    """Fetch every remote item into the cache and record its sha256.

    Labels are interleaved, so an interrupted run still leaves a balanced
    set to work with. A file that still fails after the retries is reported
    and skipped; running again resumes where it stopped.
    """
    commons = Commons(wikimedia_interval=interval)
    digests: dict[str, str] = {}
    rank: dict[str, int] = {}
    keyed = []
    for n, item in enumerate(items):
        rank[item.label] = rank.get(item.label, -1) + 1
        keyed.append((rank[item.label], LABELS.index(item.label), n))
    order = [n for *_, n in sorted(keyed)]
    for done, n in enumerate(order, 1):
        item = items[n]
        if not item.is_remote:
            continue
        path = cache_path(item, cache_dir)
        if not path.is_file() and (
            item.label not in labels or (skip_wikimedia and is_wikimedia(item.path_or_url))
        ):
            continue
        if path.is_file():
            data = path.read_bytes()
        else:
            try:
                data = commons.download(item.path_or_url)
            except (httpx.HTTPError, RuntimeError) as exc:
                print(f"  failed {item.path_or_url}: {exc}")
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        if item.sha256 and item.sha256 != digest:
            print(f"  changed upstream since the manifest: {item.source}")
        digests[item.key] = digest
        if done % 25 == 0:
            print(f"  {done}/{len(items)} cached")
    return [replace(i, sha256=i.sha256 or digests.get(i.key, "")) for i in items]


def finalize(candidates: Path, manifest: Path, cache_dir: Path, max_per_class: int) -> None:
    """Candidates minus rejects and near-duplicates, capped per class, with a fixed split.

    Near-duplicates (pHash distance <= 6, the matcher's same-photo rule)
    would put one picture on both sides of the calib/test split, so only
    the first is kept. Classes above ``max_per_class`` are trimmed so no
    single class dominates the averages.
    """
    items = read_manifest(candidates)
    reasons: dict[str, dict[str, str]] = {}
    if REJECTED.is_file():
        with REJECTED.open(encoding="utf-8", newline="") as handle:
            reasons = {row["source"]: row for row in csv.DictReader(handle)}
    kept: list[Item] = []
    hashes: list[int] = []
    for item in items:
        row = reasons.get(item.source)
        if row is not None and not row.get("relabel"):
            continue
        if row is not None:
            item = replace(item, label=row["relabel"])
        try:
            digest = perceptual_hash(load_image(item, candidates.parent, cache_dir))
        except FileNotFoundError:
            print(f"  not downloaded, skipped: {item.source}")
            continue
        twin = next(
            (k for k, h in zip(kept, hashes, strict=True) if (h ^ digest).bit_count() <= 6), None
        )
        if twin is not None:
            print(f"  near-duplicate of {twin.source}, dropped: {item.source}")
            continue
        kept.append(item)
        hashes.append(digest)
    capped: list[Item] = []
    for label in LABELS:
        # Candidates are in query order, Indian scenes first, so trimming
        # from the end keeps the most relevant ones.
        capped.extend([i for i in kept if i.label == label][:max_per_class])
    final = assign_splits(capped)
    final.sort(key=lambda i: (LABELS.index(i.label), i.split, i.source))
    write_manifest(final, manifest)
    counts = {label: sum(i.label == label for i in final) for label in LABELS}
    print(f"wrote {manifest}: {len(final)} images {counts}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_search = sub.add_parser("search", help="query Commons and write candidates.csv")
    p_search.add_argument("--per-class", type=int, default=50)
    p_search.add_argument("--per-query", type=int, default=12)
    p_search.add_argument("--out", type=Path, default=CANDIDATES)
    p_search.add_argument("--label", action="append", choices=LABELS, help="only these labels")
    p_search.add_argument(
        "--append", action="store_true", help="add to --out, skipping files already in it"
    )
    p_download = sub.add_parser("download", help="fetch a manifest's images into the cache")
    p_download.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p_download.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    p_download.add_argument(
        "--skip-wikimedia", action="store_true", help="leave uncached Commons files for later"
    )
    p_download.add_argument("--label", action="append", choices=LABELS, help="only these labels")
    p_download.add_argument(
        "--interval", type=float, default=DOWNLOAD_INTERVAL, help="seconds between Commons files"
    )
    p_final = sub.add_parser("finalize", help="candidates minus rejected.csv -> manifest.csv")
    p_final.add_argument("--candidates", type=Path, default=CANDIDATES)
    p_final.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p_final.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    p_final.add_argument("--max-per-class", type=int, default=40)
    args = parser.parse_args(argv)

    if args.command == "search":
        previous = read_manifest(args.out) if args.append and args.out.is_file() else []
        known = {i.source for i in previous}
        labels = tuple(args.label) if args.label else LABELS
        found = search(args.per_class, args.per_query, labels, known)
        items = previous + [
            Item(
                path_or_url=c.thumb_url,
                label=c.label,
                source=c.page_url,
                license=c.license,
                attribution=c.attribution,
                license_url=c.license_url,
            )
            for c in found
        ]
        write_manifest(items, args.out)
        print(f"wrote {args.out}: {len(items)} candidates")
    elif args.command == "download":
        items = read_manifest(args.manifest)
        labels = tuple(args.label) if args.label else LABELS
        updated = download(
            items,
            args.cache,
            skip_wikimedia=args.skip_wikimedia,
            labels=labels,
            interval=args.interval,
        )
        if any(a.sha256 != b.sha256 for a, b in zip(items, updated, strict=True)):
            write_manifest(updated, args.manifest)
            print(f"recorded hashes in {args.manifest}")
        cached = sum(cache_path(i, args.cache).is_file() for i in updated if i.is_remote)
        print(f"{cached}/{len(items)} images in {args.cache}")
    else:
        finalize(args.candidates, args.manifest, args.cache, args.max_per_class)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
