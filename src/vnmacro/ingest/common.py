"""Shared I/O helpers for raw data fetchers: retries, no-overwrite saves, manifests."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from vnmacro import config

OK_STATUSES = ("ok", "existing")


@dataclass(frozen=True)
class HttpSettings:
    """HTTP settings for one data source."""

    base_url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    retries: int = config.HTTP_RETRIES
    pause: float = config.HTTP_PAUSE_SECONDS
    timeout: float = config.HTTP_TIMEOUT_SECONDS


def utc_now() -> str:
    """Return the current UTC time as an ISO string (seconds)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_with_retry(
    session: requests.Session,
    url: str,
    params: dict[str, str],
    settings: HttpSettings,
    sleep: Callable[[float], None] = time.sleep,
    json_body: dict[str, Any] | None = None,
    as_json: bool = True,
) -> dict[str, Any]:
    """GET (or POST `json_body`) a URL with retries; pause after each try.

    The payload is parsed JSON if `as_json`, else the response text.
    """
    http_status, error = None, None
    for attempt in range(1, settings.retries + 2):
        try:
            if json_body is None:
                resp = session.get(
                    url,
                    params=params,
                    headers=settings.headers,
                    timeout=settings.timeout,
                )
            else:
                resp = session.post(
                    url,
                    json=json_body,
                    headers=settings.headers,
                    timeout=settings.timeout,
                )
            http_status = resp.status_code
            resp.raise_for_status()
            return {
                "content": resp.content,
                "payload": resp.json() if as_json else resp.text,
                "http_status": http_status,
                "attempts": attempt,
                "error": None,
            }
        except (requests.RequestException, ValueError) as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            sleep(settings.pause)
    return {
        "content": None,
        "payload": None,
        "http_status": http_status,
        "attempts": settings.retries + 1,
        "error": error,
    }


def save_new_file(path: Path, content: bytes) -> None:
    """Write bytes to `path`; raise FileExistsError instead of overwriting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(content)


def fetch_or_load(
    session: requests.Session,
    url: str,
    params: dict[str, str],
    path: Path,
    settings: HttpSettings,
    is_valid: Callable[[Any], bool] = lambda payload: True,
    as_json: bool = True,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[str, Any, dict[str, Any] | None]:
    """Load the payload saved at `path`, or fetch it and save the raw bytes.

    Returns (status, payload, call record). Status is 'existing' (no call made,
    record is None), 'ok' (saved), 'error' (HTTP/parse failure) or 'invalid'
    (response received but rejected by `is_valid`; not saved, so a re-run retries).
    """
    if path.exists():
        raw = path.read_bytes()
        return "existing", json.loads(raw) if as_json else raw.decode("utf-8"), None
    res = fetch_with_retry(session, url, params, settings, sleep, as_json=as_json)
    if res["error"]:
        status = "error"
    elif not is_valid(res["payload"]):
        status = "invalid"
    else:
        status = "ok"
        save_new_file(path, res["content"])
    record = {
        "file": path.name if status == "ok" else None,
        "url": url,
        "params": params,
        "status": status,
        "http_status": res["http_status"],
        "attempts": res["attempts"],
        "error": res["error"],
        "fetched_at": utc_now(),
    }
    return status, res["payload"] if status == "ok" else None, record


def load_manifest(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    """Read the manifest at `path`, or return `default` if there is none."""
    return json.loads(path.read_text()) if path.exists() else default


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Write the manifest atomically (temp file, then rename)."""
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)
