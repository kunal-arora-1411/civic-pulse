from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from scripts.eval.manifest import (
    DEFAULT_MANIFEST,
    LABELS,
    Item,
    assign_splits,
    is_open_license,
    photographer,
    read_manifest,
    write_manifest,
)


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        ("CC0", True),
        ("Public domain", True),
        ("PD-self", True),
        ("CC BY 2.0", True),
        ("CC BY-SA 4.0", True),
        ("CC BY-SA 3.0 de", True),
        ("CC BY-NC 2.0", False),
        ("CC BY-ND 4.0", False),
        ("CC BY-NC-SA 2.0", False),
        ("GFDL", False),
        ("Copyrighted free use", False),
        ("", False),
    ],
)
def test_only_open_licences_are_accepted(name: str, ok: bool) -> None:
    assert is_open_license(name) is ok


def _item(n: int, label: str, author: str | None = None) -> Item:
    return Item(
        path_or_url=f"https://example.invalid/{label}/{n}.jpg",
        label=label,
        source=f"https://commons.wikimedia.org/wiki/File:{label}_{n}.jpg",
        license="CC0",
        attribution=f"{author or f'Author {label} {n}'} / Wikimedia Commons",
    )


def test_splits_are_stratified_deterministic_and_sticky() -> None:
    items = [_item(n, label) for label in LABELS for n in range(9)]
    first = assign_splits(items)
    assert first == assign_splits(list(reversed(items)))[::-1]
    for label in LABELS:
        tests = [i for i in first if i.label == label and i.split == "test"]
        assert len(tests) in (4, 5)
    # Adding images later never moves an existing one between splits.
    grown = assign_splits([*first, _item(99, "pothole")])
    assert grown[: len(first)] == first


def test_one_photographers_series_stays_on_one_side() -> None:
    series = [_item(n, "waterlogging", author="Prolific") for n in range(4)]
    others = [_item(n, "waterlogging") for n in range(10, 18)]
    split = assign_splits([*series, *others])
    assert len({i.split for i in split if "Prolific" in i.attribution}) == 1
    tests = sum(i.split == "test" for i in split)
    assert 4 <= tests <= 8


def test_photographer_comes_from_the_flickr_account_or_the_credit() -> None:
    flickr = replace(
        _item(1, "waste"),
        source="https://www.flickr.com/photos/12345678@N00/987654321",
        attribution="Display Name / Flickr (via Openverse)",
    )
    assert photographer(flickr) == "flickr:12345678@N00"
    assert photographer(_item(2, "waste", author="Jane Doe")) == "author:jane doe"


def test_manifest_round_trips(tmp_path: Path) -> None:
    items = assign_splits([_item(n, "waste") for n in range(4)])
    path = tmp_path / "m.csv"
    write_manifest(items, path)
    assert read_manifest(path) == items


def test_unknown_labels_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "m.csv"
    write_manifest([replace(_item(1, "waste"), label="graffiti")], path)
    with pytest.raises(ValueError, match="unknown label"):
        read_manifest(path)


def test_committed_manifest_is_open_licensed_and_split() -> None:
    if not DEFAULT_MANIFEST.is_file():
        pytest.skip("no committed manifest yet")
    items = read_manifest(DEFAULT_MANIFEST)
    assert {i.label for i in items} == set(LABELS)
    for item in items:
        assert is_open_license(item.license), item.source
        assert item.attribution
        assert item.source.startswith(
            ("https://commons.wikimedia.org/", "https://www.flickr.com/photos/")
        )
        assert item.split in ("calib", "test")
        assert len(item.sha256) == 64
    assert len({i.path_or_url for i in items}) == len(items)
