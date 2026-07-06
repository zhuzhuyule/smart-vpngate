"""Default network transport for Discovery.

Kept separate from :mod:`smart_vpngate.discovery` so the Discovery pipeline
stays pure and offline-testable (it takes a ``fetcher`` callable). This module
provides the real-world fetcher that talks to the VPNGate API over HTTPS, with
the same certificate-verify fallback the legacy manager uses.
"""

from __future__ import annotations

import ssl
import urllib.request

DEFAULT_API_URL = "https://www.vpngate.net/api/iphone/"


def http_fetcher(url: str = DEFAULT_API_URL, timeout: int = 30):
    """Return a zero-arg callable that downloads ``url`` and returns its text.

    Tries, in order: HTTPS with cert verification, HTTPS without verification,
    then plain HTTP — mirroring the legacy ``fetch_candidates`` fallback so
    discovery keeps working on VPS boxes with broken CA stores. Honors the
    standard ``HTTPS_PROXY`` / ``HTTP_PROXY`` environment variables via urllib.
    """

    def _get(target: str, context: ssl.SSLContext | None) -> str:
        req = urllib.request.Request(target, headers={"User-Agent": "smart-vpngate/2.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")

    def fetch() -> str:
        insecure = ssl.create_default_context()
        insecure.check_hostname = False
        insecure.verify_mode = ssl.CERT_NONE

        attempts = [(url, None), (url, insecure)]
        if url.startswith("https://"):
            attempts.append((url.replace("https://", "http://", 1), None))

        last_err: Exception | None = None
        for target, ctx in attempts:
            try:
                return _get(target, ctx)
            except Exception as exc:  # noqa: BLE001 - fall through to next attempt
                last_err = exc
        raise RuntimeError(f"Failed to fetch VPNGate feed from {url}: {last_err}")

    return fetch
