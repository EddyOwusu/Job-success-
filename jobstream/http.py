"""Shared HTTP session with retries, polite rate limiting and a disk cache."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "jobstream/0.1 (personal job search assistant)"

_session: Optional[requests.Session] = None
_lock = threading.Lock()
_last_call: dict[str, float] = {}


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        retry = Retry(total=3, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=None)
        s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=16))
        s.headers["User-Agent"] = USER_AGENT
        _session = s
    return _session


def _throttle(host: str, min_interval: float) -> None:
    with _lock:
        wait = _last_call.get(host, 0) + min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()


def get_json(url: str, *, params: dict | None = None, auth=None, min_interval: float = 0.25,
             timeout: float = 30, cache_dir: Path | None = None, cache_ttl: float = 0) -> Any:
    """GET a URL and decode JSON. Returns None on 404."""
    cache_file = None
    if cache_dir and cache_ttl:
        key = hashlib.sha1(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
        cache_file = cache_dir / f"{key}.json"
        if cache_file.exists() and time.time() - cache_file.stat().st_mtime < cache_ttl:
            return json.loads(cache_file.read_text())
    host = url.split("/")[2]
    _throttle(host, min_interval)
    r = session().get(url, params=params, auth=auth, timeout=timeout)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    if cache_file:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data))
    return data
