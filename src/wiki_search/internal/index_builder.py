#
# index_builder.py
#
from __future__ import annotations

import gzip
import logging
import os
import re
import sqlite3
import string
import time
import zlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable

import requests
import urllib3
from filelock import FileLock
from tqdm import tqdm

from .http import DEFAULT_TIMEOUT
from .lemmatizer import Lemmatizer
from .text import normalize_text

logger = logging.getLogger(__name__)

DUMP_URL = "https://dumps.wikimedia.org/ruwiki/latest/ruwiki-latest-all-titles-in-ns0.gz"
DB_NAME = "wiki-titles.db"
ARCHIVE_NAME = "ru-wiki-latest-all-titles.gz"
LOCK_NAME = "wiki-titles.lock"

SCHEMA_VERSION = 2

MIN_FTS_LEN = 3

_TITLE_PATTERN = re.compile(
    r"^[0-9A-Za-z\u00C0-\u024F\u0400-\u04FF\s"
    + re.escape(string.punctuation + "–—−«»„“”‘’…№°·")
    + r"]+$"
)


def is_indexable_title(title: str) -> bool:
    return bool(title) and _TITLE_PATTERN.match(title) is not None


def read_meta(db_path: Path) -> dict[str, str] | None:
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
        try:
            meta = dict(conn.execute("SELECT key, value FROM meta"))
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return meta if meta.get("schema_version") == str(SCHEMA_VERSION) else None


def download_dump(
    session: requests.Session,
    url: str,
    dest: Path,
    *,
    timeout=DEFAULT_TIMEOUT,
    attempts: int = 3,
    show_progress: bool = True,
) -> None:
    part = dest.with_name(dest.name + ".part")
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with session.get(url, stream=True, timeout=timeout) as response:
                response.raise_for_status()
                expected = int(response.headers.get("Content-Length") or 0)
                written = 0
                with open(part, "wb") as f, tqdm(
                    total=expected or None, unit="B", unit_scale=True,
                    desc="Downloading dump", disable=not show_progress,
                ) as bar:
                    for chunk in response.raw.stream(1 << 20, decode_content=False):
                        f.write(chunk)
                        written += len(chunk)
                        bar.update(len(chunk))
                if expected and written != expected:
                    raise OSError(f"Incomplete download: {written} of {expected} bytes")
                last_modified = response.headers.get("Last-Modified")
            os.replace(part, dest)
            if last_modified:
                try:
                    ts = parsedate_to_datetime(last_modified).timestamp()
                    os.utime(dest, (ts, ts))
                except (TypeError, ValueError):
                    pass
            return
        except (requests.RequestException, urllib3.exceptions.HTTPError, OSError) as e:
            last_error = e
            part.unlink(missing_ok=True)
            logger.warning("Download attempt %d/%d failed: %s", attempt, attempts, e)
            if attempt < attempts:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Failed to download {url}: {last_error}") from last_error


def _remove_sqlite_files(path: Path) -> None:
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def build_index(
    db_path: Path,
    archive_path: Path,
    lemmatizer: Lemmatizer,
    *,
    source_url: str = DUMP_URL,
    batch_size: int = 50_000,
    show_progress: bool = True,
) -> int:
    tmp_path = db_path.with_name(f"{db_path.name}.tmp-{os.getpid()}")
    _remove_sqlite_files(tmp_path)
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(tmp_path)
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute('CREATE VIRTUAL TABLE titles_fts USING fts5(title, lemmas, tokenize="trigram")')
        conn.execute("CREATE TABLE short_titles (norm TEXT NOT NULL, title TEXT NOT NULL)")
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

        fts_batch: list[tuple[str, str]] = []
        short_batch: list[tuple[str, str]] = []
        fts_count = short_count = 0

        def flush() -> None:
            conn.executemany("INSERT INTO titles_fts(title, lemmas) VALUES (?, ?)", fts_batch)
            conn.executemany("INSERT INTO short_titles(norm, title) VALUES (?, ?)", short_batch)
            conn.commit()
            fts_batch.clear()
            short_batch.clear()

        with gzip.open(archive_path, "rt", encoding="utf-8") as f:
            for line in tqdm(f, desc="Building index", unit="line", disable=not show_progress):
                title = line.rstrip("\n").replace("_", " ").strip()
                if not is_indexable_title(title):
                    continue
                if len(title) < MIN_FTS_LEN:
                    short_batch.append((normalize_text(title), title))
                    short_count += 1
                else:
                    fts_batch.append((title, lemmatizer.lemmatize_text(title)))
                    fts_count += 1
                if len(fts_batch) + len(short_batch) >= batch_size:
                    flush()
        flush()

        conn.execute("CREATE INDEX idx_short_titles_norm ON short_titles(norm)")
        conn.execute("INSERT INTO titles_fts(titles_fts) VALUES ('optimize')")
        dump_ts = archive_path.stat().st_mtime
        conn.executemany("INSERT INTO meta(key, value) VALUES (?, ?)", [
            ("schema_version", str(SCHEMA_VERSION)),
            ("row_count", str(fts_count)),
            ("short_count", str(short_count)),
            ("source_url", source_url),
            ("dump_last_modified", datetime.fromtimestamp(dump_ts, timezone.utc).isoformat()),
            ("built_at", datetime.now(timezone.utc).isoformat()),
        ])
        conn.commit()
        conn.close()
        conn = None

        with open(tmp_path, "rb+") as fh:
            os.fsync(fh.fileno())
        os.replace(tmp_path, db_path)
        return fts_count + short_count
    except BaseException:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        _remove_sqlite_files(tmp_path)
        raise


def ensure_index(
    data_dir: Path,
    lemmatizer: Lemmatizer,
    *,
    session_factory: Callable[[], requests.Session] | None = None,
    dump_url: str = DUMP_URL,
    show_progress: bool = True,
    timeout=DEFAULT_TIMEOUT,
) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / DB_NAME
    if read_meta(db_path) is not None:
        return db_path

    with FileLock(str(data_dir / LOCK_NAME)):
        if read_meta(db_path) is not None:
            return db_path
        if db_path.exists():
            logger.warning("Index %s is outdated or corrupted, rebuilding", db_path)
            _remove_sqlite_files(db_path)

        archive_path = data_dir / ARCHIVE_NAME
        if not archive_path.exists():
            if session_factory is None:
                raise ValueError("A user_agent or email is required to download the Wikipedia dump")
            download_dump(session_factory(), dump_url, archive_path, timeout=timeout,
                          show_progress=show_progress)

        try:
            build_index(db_path, archive_path, lemmatizer,
                        source_url=dump_url, show_progress=show_progress)
        except (OSError, EOFError, zlib.error) as e:
            archive_path.unlink(missing_ok=True)
            raise RuntimeError(f"Failed to build index (archive removed): {e}") from e
        except Exception as e:
            raise RuntimeError(f"Failed to build index: {e}") from e

        archive_path.unlink(missing_ok=True)
    return db_path
