from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from typing import Any

import requests

from .internal import (
    PROJECT_NAME, PROJECT_VERSION, RankingConfig, WikiClient, WikiTitleFinder, is_valid_email,
)
from .internal.http import DEFAULT_TIMEOUT, make_session
from .internal.text import make_summary

_PROJECT_URL = "https://github.com/KvaytG/ru-wiki-search"


@dataclass(frozen=True)
class SearchResult:
    title: str                       # заголовок статьи (после разрешения редиректов)
    url: str                         # url
    summary: str | None              # саммари
    matched_title: str               # заголовок из локального индекса, который совпал с запросом
    description: str | None = None   # короткое описание из Викиданных
    is_disambiguation: bool = False  # страница значений

    def __getitem__(self, key: str) -> Any:
        if key in {f.name for f in dataclasses.fields(self)}:
            return getattr(self, key)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class WikiSearcher:
    """
    Умный поиск по русской Википедии.

    :param email: контактный e-mail для User-Agent (требование Викимедиа). Либо передайте
        готовый ``user_agent``.
    :param data_dir: где хранить индекс (по умолчанию — кэш пользователя, см. README).
    :param ranking: веса формулы ранжирования.
    :param summary_sentences: сколько предложений оставлять в summary.
    :param max_summary_chars: ограничение длины summary (по границе слова), None — без ограничения.
    :param fallback_candidates: сколько лучших заголовков пробовать, если статья
        ненайденного заголовка не существует.
    :param session: свой ``requests.Session`` (кэш, прокси); по умолчанию создаётся собственная.
    :param load_index: загружать индекс сразу. Первый запуск скачивает дамп и строит индекс
        (минуты); передайте False и вызовите ``load()`` позже, если конструктор не должен блокироваться.
    """
    def __init__(
        self,
        email: str | None = None,
        *,
        user_agent: str | None = None,
        data_dir: str | os.PathLike | None = None,
        ranking: RankingConfig | None = None,
        summary_sentences: int = 2,
        max_summary_chars: int | None = None,
        fallback_candidates: int = 5,
        timeout=DEFAULT_TIMEOUT,
        session: requests.Session | None = None,
        show_progress: bool = True,
        load_index: bool = True,
    ):
        if user_agent is None:
            if email is None:
                raise ValueError("Provide either 'email' or 'user_agent'.")
            if not is_valid_email(email):
                raise ValueError(f"'{email}' is not a valid email address.")
            user_agent = f"{PROJECT_NAME}/{PROJECT_VERSION} ({_PROJECT_URL}; {email})"

        self._owns_session = session is None
        self._session = session or make_session(user_agent)
        if session is not None and "User-Agent" not in session.headers:
            self._session.headers["User-Agent"] = user_agent

        self._client = WikiClient(self._session, timeout=timeout)
        self._finder = WikiTitleFinder(
            user_agent, data_dir, ranking=ranking, session=self._session,
            show_progress=show_progress, timeout=timeout,
        )
        self._summary_sentences = summary_sentences
        self._max_summary_chars = max_summary_chars
        self._fallback_candidates = max(1, fallback_candidates)
        if load_index:
            self.load()

    def load(self) -> None:
        self._finder.load()

    def close(self) -> None:
        self._finder.close()
        if self._owns_session:
            self._session.close()

    def __enter__(self) -> "WikiSearcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def index_info(self) -> dict[str, str]:
        return self._finder.info()

    def suggest(self, query: str, limit: int = 5) -> list[str]:
        return self._finder.find(query, max(1, limit)) if query.strip() else []

    def _fetch(self, matched_title: str) -> SearchResult | None:
        page = self._client.get_summary(matched_title)
        if page is None:
            return None
        return SearchResult(
            title=page.title,
            url=page.url,
            summary=make_summary(page.extract, self._summary_sentences, self._max_summary_chars),
            matched_title=matched_title,
            description=page.description,
            is_disambiguation=page.is_disambiguation,
        )

    def search(self, query: str) -> SearchResult | None:
        for title in self.suggest(query, self._fallback_candidates):
            result = self._fetch(title)
            if result is not None:
                return result
        return None

    def search_many(self, query: str, limit: int = 5) -> list[SearchResult]:
        limit = max(1, limit)
        results: list[SearchResult] = []
        seen: set[str] = set()
        for title in self.suggest(query, max(limit * 3, self._fallback_candidates)):
            result = self._fetch(title)
            if result is None or result.title in seen:
                continue
            seen.add(result.title)
            results.append(result)
            if len(results) >= limit:
                break
        return results
