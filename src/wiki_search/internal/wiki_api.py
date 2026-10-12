#
# wiki_api.py
#
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import requests

from .http import DEFAULT_TIMEOUT

SUMMARY_URL = "https://ru.wikipedia.org/api/rest_v1/page/summary/{title}"
ARTICLE_URL = "https://ru.wikipedia.org/wiki/{title}"


class WikiApiError(RuntimeError):
    """Сетевая ошибка или неожиданный ответ API (но не «страница не найдена»)."""


@dataclass(frozen=True)
class PageSummary:
    title: str                 # заголовок статьи после разрешения редиректов
    url: str                   # url
    extract: str               # вводный текст статьи (может быть пустым)
    description: str | None    # короткое описание из Викиданных
    is_disambiguation: bool    # страница значений


class WikiClient:
    def __init__(self, session: requests.Session, timeout=DEFAULT_TIMEOUT, url_template: str = SUMMARY_URL):
        self._session = session
        self._timeout = timeout
        self._url_template = url_template

    def get_summary(self, title: str) -> PageSummary | None:
        url = self._url_template.format(title=quote(title.replace(" ", "_"), safe=""))
        try:
            response = self._session.get(
                url, timeout=self._timeout, headers={"Accept": "application/json"}
            )
        except requests.RequestException as e:
            raise WikiApiError(f"Request failed for '{title}': {e}") from e

        if response.status_code == 404:
            return None
        try:
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as e:
            raise WikiApiError(f"Unexpected response for '{title}': {e}") from e

        kind = str(data.get("type", ""))
        if "not_found" in kind:
            return None

        titles = data.get("titles") or {}
        page_title = (
            titles.get("normalized")
            or data.get("title")
            or str(titles.get("canonical", title)).replace("_", " ")
        )
        page_url = ((data.get("content_urls") or {}).get("desktop") or {}).get("page") or \
            ARTICLE_URL.format(title=quote(page_title.replace(" ", "_"), safe=":/()_,!*'~-."))
        return PageSummary(
            title=page_title,
            url=page_url,
            extract=data.get("extract") or "",
            description=data.get("description"),
            is_disambiguation=(kind == "disambiguation"),
        )
