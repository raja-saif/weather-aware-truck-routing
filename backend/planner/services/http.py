"""Shared HTTP session for third-party APIs: pooled connections, retries, timeouts."""

from __future__ import annotations

import logging
import threading
from urllib.parse import urlsplit

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

# (connect, read) seconds. Kept short: every caller has a fallback or a clear
# error, and a slow public API must not hold a request for minutes.
DEFAULT_TIMEOUT = (5, 20)

_local = threading.local()


def _log_response(resp: requests.Response, *args, **kwargs) -> None:
    host = urlsplit(resp.url).netloc
    ms = round(resp.elapsed.total_seconds() * 1000)
    level = logging.WARNING if resp.status_code >= 400 else logging.INFO
    log.log(level, "upstream %s %s -> %s in %d ms", resp.request.method, host, resp.status_code, ms)


def session() -> requests.Session:
    """One session per thread (requests.Session is not guaranteed thread-safe)."""
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        # One quick retry for transient gateway errors only. 429 is not retried and
        # Retry-After is not honoured: a rate-limited provider fails fast so the
        # caller can fall back instead of sleeping inside the request.
        retry = Retry(
            total=1,
            backoff_factor=0.5,
            status_forcelist=(502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
            respect_retry_after_header=False,
            raise_on_status=False,  # hand the final 5xx to the caller for a precise message
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers["User-Agent"] = settings.HTTP_USER_AGENT
        s.hooks["response"].append(_log_response)
        _local.session = s
    return s
