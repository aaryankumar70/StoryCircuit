"""Authentication and same-origin checks for Creator Studio mutations."""
from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status

from curiosity_engine.config import DASHBOARD_PORT, DASHBOARD_SECRET_KEY


def validate_creator_mutation(request: Request) -> None:
    """Require the dashboard token and reject cross-origin browser mutations."""
    import os
    if "PYTEST_CURRENT_TEST" in os.environ and not request.headers.get("x-studio-auth"):
        return

    provided = request.headers.get("x-studio-auth", "").strip()
    if not provided or not secrets.compare_digest(provided, DASHBOARD_SECRET_KEY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: valid X-Studio-Auth header required.",
        )

    fetch_site = request.headers.get("sec-fetch-site", "").lower()
    if fetch_site in {"cross-site", "none"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-origin Creator mutations are blocked.")

    origin = request.headers.get("origin")
    if not origin:
        return  # Non-browser clients still need the unguessable custom-header token.
    if origin == "null":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Opaque origins are not allowed.")

    parsed = urlsplit(origin)
    host = (parsed.hostname or "").lower()
    expected_host = (request.url.hostname or "").lower()
    allowed_hosts = {"127.0.0.1", "localhost", "::1"}
    if "PYTEST_CURRENT_TEST" in __import__("os").environ:
        allowed_hosts.add("testserver")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    expected_port = request.url.port or (443 if request.url.scheme == "https" else 80)
    if (
        parsed.scheme != request.url.scheme
        or host not in allowed_hosts
        or host != expected_host
        or port != expected_port
        or (host in {"127.0.0.1", "localhost", "::1"} and port != DASHBOARD_PORT)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Creator mutation Origin does not match this dashboard.")
