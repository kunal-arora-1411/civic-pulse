"""Write the OpenAPI document to apps/api/openapi.json.

    uv run python scripts/export_openapi.py          # write the file
    uv run python scripts/export_openapi.py --check  # fail if it is stale (CI)

The frontend generates its TypeScript client from the committed file, so
regenerate and commit it with any API change.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "openapi.json"
sys.path.insert(0, str(ROOT))

# Building the app reads settings, but exporting the schema never connects to
# anything. These placeholders only fill gaps; real values win if present.
_PLACEHOLDERS = {
    "DATABASE_URL": "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder",
    "JWT_SECRET": "openapi-export-placeholder-not-a-secret-000000",
    "OTP_HMAC_SECRET": "openapi-export-placeholder-not-a-secret-000000",
    "TOTP_ENCRYPTION_KEY": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    "S3_ACCESS_KEY": "openapi-export-placeholder",
    "S3_SECRET_KEY": "openapi-export-placeholder",
}
for name, value in _PLACEHOLDERS.items():
    os.environ.setdefault(name, value)


def build_schema() -> dict[str, Any]:
    from app.main import create_app

    return create_app().openapi()


def render(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if openapi.json is stale")
    args = parser.parse_args()

    rendered = render(build_schema())
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != rendered:
            print("openapi.json is out of date: run scripts/export_openapi.py", file=sys.stderr)
            return 1
        print("openapi.json is up to date")
        return 0

    OUTPUT.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
