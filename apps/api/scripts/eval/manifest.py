"""The labelled-image manifest shared by the evaluation scripts.

A UTF-8 CSV with a header row. The first five columns are the contract's
(Phase 2 contract, section H); the rest are optional:

    path_or_url   local path (relative to the manifest) or http(s) URL of the image
    label         pothole | waste | waterlogging | streetlight | drainage | not_civic
    source        page describing the image (the Commons file page or Flickr photo page)
    license       short licence name as published, e.g. "CC BY-SA 4.0"
    attribution   author / credit line, plain text
    license_url   link to the licence text
    sha256        hash of the bytes fetched when the manifest was built; a
                  mismatch means the upstream file changed and is reported
    split         calib | test; fixed so every run evaluates the same held-out set,
                  stratified by label and grouped by photographer

Images are cached under ``apps/api/.eval-cache/`` (git-ignored) by the hash
of their URL, so the manifest is committed and the pictures are not.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from PIL import Image

EVAL_DIR = Path(__file__).resolve().parent
API_ROOT = EVAL_DIR.parents[1]
DEFAULT_MANIFEST = EVAL_DIR / "manifest.csv"
DEFAULT_CACHE = API_ROOT / ".eval-cache"

LABELS = ("pothole", "waste", "waterlogging", "streetlight", "drainage", "not_civic")
SPLITS = ("calib", "test")
# Commons' LicenseShortName values: "CC BY-SA 4.0", "CC BY 2.0 de", "CC0", "Public domain".
_OPEN_LICENSE = re.compile(
    r"^(CC0( 1\.0)?|Public domain|PD(-[\w-]+)?|CC BY(-SA)? \d\.\d( [a-z]{2,}(-[a-z]{2,})?)?)$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Item:
    path_or_url: str
    label: str
    source: str
    license: str
    attribution: str
    license_url: str = ""
    sha256: str = ""
    split: str = ""

    @property
    def is_remote(self) -> bool:
        return self.path_or_url.startswith(("http://", "https://"))

    @property
    def key(self) -> str:
        """Stable short id, used for cache file names and deterministic splits."""
        return hashlib.sha1(self.path_or_url.encode(), usedforsecurity=False).hexdigest()[:16]


COLUMNS = [f.name for f in fields(Item)]


def is_open_license(name: str) -> bool:
    """CC0, public domain, CC BY or CC BY-SA (any version or port); nothing NC, ND or GFDL-only."""
    return bool(_OPEN_LICENSE.match(" ".join(name.split())))


def read_manifest(path: Path = DEFAULT_MANIFEST) -> list[Item]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = {"path_or_url", "label", "source", "license", "attribution"} - set(
            reader.fieldnames or []
        )
        if missing:
            raise ValueError(f"{path}: missing columns {sorted(missing)}")
        items = [Item(**{k: (row.get(k) or "").strip() for k in COLUMNS}) for row in reader]
    for item in items:
        if item.label not in LABELS:
            raise ValueError(f"{path}: unknown label {item.label!r} for {item.path_or_url}")
        if item.split and item.split not in SPLITS:
            raise ValueError(f"{path}: unknown split {item.split!r} for {item.path_or_url}")
    return items


def write_manifest(items: Iterable[Item], path: Path = DEFAULT_MANIFEST) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for item in items:
            writer.writerow(asdict(item))


def photographer(item: Item) -> str:
    """Who took the picture: the Flickr account, else the credited author.

    Photographers tend to upload series of one scene, and a series split
    across calib and test would leak; splits are made per photographer.
    """
    flickr = re.match(r"https?://(?:www\.)?flickr\.com/photos/([^/]+)/", item.source)
    if flickr:
        return f"flickr:{flickr.group(1)}"
    return "author:" + item.attribution.split(" / ")[0].strip().lower()


def assign_splits(items: Sequence[Item], test_fraction: float = 0.5) -> list[Item]:
    """Stratified, grouped, deterministic calib/test split.

    Within each label, whole photographer groups go to one side, smallest
    hash first, until the test side holds about ``test_fraction`` of the
    label. Rows that already have a split keep it.
    """
    out: dict[str, Item] = {item.key: item for item in items}
    for label in LABELS:
        unsplit = [i for i in items if i.label == label and not i.split]
        groups: dict[str, list[Item]] = {}
        for item in unsplit:
            groups.setdefault(photographer(item), []).append(item)
        order = sorted(
            groups,
            key=lambda g: hashlib.sha1(g.encode(), usedforsecurity=False).hexdigest(),
        )
        target = round(len(unsplit) * test_fraction)
        in_test = 0
        for group in order:
            members = groups[group]
            # Take a group for test if it brings the count closer to the target.
            take = abs(target - (in_test + len(members))) < abs(target - in_test)
            if take:
                in_test += len(members)
            for item in members:
                split = "test" if take else "calib"
                out[item.key] = Item(**{**asdict(item), "split": split})
    return [out[item.key] for item in items]


def cache_path(item: Item, cache_dir: Path = DEFAULT_CACHE) -> Path:
    suffix = Path(item.path_or_url.split("?")[0]).suffix.lower() or ".jpg"
    return cache_dir / item.label / f"{item.key}{suffix}"


def load_image(item: Item, manifest_dir: Path, cache_dir: Path = DEFAULT_CACHE) -> Image.Image:
    """Open an item's image from the cache (remote) or relative to the manifest (local)."""
    path = cache_path(item, cache_dir) if item.is_remote else manifest_dir / item.path_or_url
    if not path.is_file():
        raise FileNotFoundError(f"{path} (run scripts/eval/fetch_commons.py download first)")
    data = path.read_bytes()
    image = Image.open(io.BytesIO(data))
    image.load()
    return image.convert("RGB")
