#
# wiki_title_finder.py
#
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from dataclasses import dataclass, field

import requests

from .http import DEFAULT_TIMEOUT, make_session
from .index_builder import DUMP_URL, MIN_FTS_LEN, ensure_index
from .lemmatizer import Lemmatizer
from .paths import resolve_data_dir
from .ranking import RankingConfig
from .scoring import Features, combine, extract_features
from .text import collapse_spaces, normalize_text, split_words

logger = logging.getLogger(__name__)

CANDIDATE_LIMIT = 1000


def _phrase(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'


@dataclass(frozen=True)
class CandidateSet:
    query_lower: str
    query_lemmas: str
    rows: list[tuple[str, str]] = field(default_factory=list)


class WikiTitleFinder:
    def __init__(
        self,
        user_agent: str | None = None,
        data_dir: str | os.PathLike | None = None,
        *,
        ranking: RankingConfig | None = None,
        dump_url: str = DUMP_URL,
        session: requests.Session | None = None,
        show_progress: bool = True,
        timeout=DEFAULT_TIMEOUT,
    ):
        self._user_agent = user_agent
        self._data_dir = resolve_data_dir(data_dir)
        self._ranking = ranking or RankingConfig()
        self._dump_url = dump_url
        self._session = session
        self._show_progress = show_progress
        self._timeout = timeout
        self._lemmatizer = Lemmatizer()
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    @property
    def ranking(self) -> RankingConfig:
        return self._ranking

    @property
    def data_dir(self):
        return self._data_dir

    def load(self) -> None:
        if self._conn is not None:
            return

        owned: list[requests.Session] = []

        def session_factory() -> requests.Session:
            if self._session is not None:
                return self._session
            session = make_session(self._user_agent)
            owned.append(session)
            return session

        has_ua = self._session is not None or bool(self._user_agent)
        try:
            db_path = ensure_index(
                self._data_dir, self._lemmatizer,
                session_factory=session_factory if has_ua else None,
                dump_url=self._dump_url, show_progress=self._show_progress,
                timeout=self._timeout,
            )
        finally:
            for session in owned:
                session.close()
        self._conn = sqlite3.connect(
            f"{db_path.as_uri()}?mode=ro", uri=True, check_same_thread=False
        )

    def close(self) -> None:
        conn, self._conn = getattr(self, "_conn", None), None
        if conn is not None:
            conn.close()

    def __enter__(self) -> "WikiTitleFinder":
        self.load()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def info(self) -> dict[str, str]:
        self.load()
        with self._lock:
            return dict(self._conn.execute("SELECT key, value FROM meta"))  # type: ignore[union-attr]

    def _query(self, sql: str, params: tuple) -> list[tuple]:
        assert self._conn is not None
        with self._lock:
            try:
                return self._conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError as e:
                logger.debug("FTS query failed (%s): %s", params, e)
                return []

    def _fts(self, match: str, limit: int) -> list[tuple]:
        return self._query(
            "SELECT title, lemmas FROM titles_fts WHERE titles_fts MATCH ? ORDER BY rank LIMIT ?",
            (match, limit),
        )

    def _short(self, norm: str) -> list[tuple[str, str]]:
        rows = self._query("SELECT title FROM short_titles WHERE norm = ?", (norm,))
        return [(t, self._lemmatizer.lemmatize_text(t)) for (t,) in rows]

    def candidates(self, query: str, limit: int = CANDIDATE_LIMIT) -> CandidateSet:
        self.load()
        q = query.strip()
        words = split_words(q)
        if not words:
            return CandidateSet(q.lower(), "")

        query_lemmas = self._lemmatizer.lemmatize_text(q)
        rows = self._fetch(words, collapse_spaces(normalize_text(q)), limit)
        return CandidateSet(q.lower(), query_lemmas, rows)

    def _fetch(self, words: list[str], norm_query: str, limit: int) -> list[tuple]:
        long_words = [w for w in words if len(w) >= MIN_FTS_LEN]
        if long_words:
            groups = []
            for w in dict.fromkeys(long_words):
                lemma = self._lemmatizer.lemma(w)
                alts = [w] if lemma == w or len(lemma) < MIN_FTS_LEN else [w, lemma]
                groups.append("(" + " OR ".join(_phrase(a) for a in alts) + ")")
            rows = self._fts(" AND ".join(groups), limit)
            if not rows and len(groups) > 1:
                rows = self._fts(" OR ".join(groups), limit)
            return rows
        if len(norm_query) >= MIN_FTS_LEN:
            return self._fts(_phrase(norm_query), limit)
        return self._short(norm_query)

    def has_title(self, title: str) -> bool:
        self.load()
        norm = collapse_spaces(normalize_text(title))
        words = split_words(title)
        if not words:
            return False
        rows = self._fetch(words, norm, CANDIDATE_LIMIT)
        return any(collapse_spaces(normalize_text(t)) == norm for t, _ in rows)

    @staticmethod
    def features(cands: CandidateSet) -> list[Features]:
        return [
            extract_features(cands.query_lower, cands.query_lemmas, title, lemmas)
            for title, lemmas in cands.rows
        ]

    def rank(self, cands: CandidateSet, top_n: int = 10) -> list[str]:
        scores = [combine(f, self._ranking) for f in self.features(cands)]
        order = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)  # стабильно
        return [cands.rows[i][0] for i in order[:top_n]]

    def find(self, query: str, top_n: int = 10) -> list[str]:
        return self.rank(self.candidates(query), top_n)
