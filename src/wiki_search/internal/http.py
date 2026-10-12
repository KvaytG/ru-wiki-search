#
# http.py
#
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT = (10.0, 60.0)  # (подключение, чтение), секунды


def make_session(user_agent: str | None) -> requests.Session:
    session = requests.Session()
    if user_agent:
        session.headers["User-Agent"] = user_agent
    retry = Retry(
        total=4,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
