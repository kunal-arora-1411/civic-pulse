"""Print a fresh VAPID key pair for Web Push, in the form settings expect.

    uv run python scripts/vapid_keys.py

VAPID_PUBLIC_KEY is the uncompressed P-256 point browsers subscribe with;
VAPID_PRIVATE_KEY is the raw private scalar. Both are base64url without
padding. Keep the private key secret; rotating it invalidates every browser
subscription, so people have to allow notifications again.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def main() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    print(f"VAPID_PUBLIC_KEY={_b64(public)}")
    print(f"VAPID_PRIVATE_KEY={_b64(private)}")


if __name__ == "__main__":
    main()
