import gzip
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from conftest import TITLES, write_dump
from wiki_search.internal import WikiTitleFinder, index_builder
from wiki_search.internal.index_builder import (
    ARCHIVE_NAME, DB_NAME, SCHEMA_VERSION, download_dump, ensure_index,
    is_indexable_title, read_meta,
)
from wiki_search.internal.lemmatizer import Lemmatizer


def titles_in(db):
    conn = sqlite3.connect(db)
    fts = [r[0] for r in conn.execute("SELECT title FROM titles_fts")]
    short = [r[0] for r in conn.execute("SELECT title FROM short_titles")]
    conn.close()
    return fts, short


def test_index_contents(index_dir):
    fts, short = titles_in(index_dir / DB_NAME)
    assert "Python" in fts and "Скайп (Skype)" in fts and "iPhone" in fts and "Wi-Fi" in fts  # латиница
    assert "Мир" in fts and "МИР" in fts                                                       # без дедупа по регистру
    assert sorted(short) == ["ИИ", "РА", "Ра"]                                                  # короткие отдельно
    assert "漢字" not in fts and "Страница с иероглифом 漢" not in fts                         # иероглифы отсекаются
    meta = read_meta(index_dir / DB_NAME)
    assert meta["schema_version"] == str(SCHEMA_VERSION)
    assert int(meta["row_count"]) == len(fts) and int(meta["short_count"]) == 3
    assert not (index_dir / ARCHIVE_NAME).exists()  # архив удалён после успешной сборки


@pytest.mark.parametrize("title,ok", [("Python", True), ("Éclair", True), ("«Ёлка» — 1999", True),
                                      ("漢字", False), ("", False), ("Страница 漢", False)])
def test_title_filter(title, ok):
    assert is_indexable_title(title) is ok


def test_interrupted_build_leaves_nothing_and_recovers(tmp_path):
    write_dump(tmp_path)
    lem = Lemmatizer()
    calls = {"n": 0}
    original = lem.lemmatize_text

    def boom(text):
        calls["n"] += 1
        if calls["n"] == 4:
            raise KeyboardInterrupt
        return original(text)

    lem.lemmatize_text = boom
    with pytest.raises(KeyboardInterrupt):
        ensure_index(tmp_path, lem, show_progress=False)

    assert not (tmp_path / DB_NAME).exists()                 # битой БД нет
    assert not list(tmp_path.glob("*.tmp-*"))                # временных файлов нет
    assert (tmp_path / ARCHIVE_NAME).exists()                # архив сохранён: заново качать не надо

    db = ensure_index(tmp_path, Lemmatizer(), show_progress=False)   # повторный запуск чинит всё сам
    assert read_meta(db) is not None and not (tmp_path / ARCHIVE_NAME).exists()


def test_failed_build_wraps_error_and_keeps_archive(tmp_path, monkeypatch):
    write_dump(tmp_path)

    def broken(*a, **k):
        raise sqlite3.OperationalError("disk is on fire")

    monkeypatch.setattr(index_builder, "build_index", broken)
    with pytest.raises(RuntimeError) as e:
        ensure_index(tmp_path, Lemmatizer(), show_progress=False)
    assert isinstance(e.value.__cause__, sqlite3.OperationalError)
    assert (tmp_path / ARCHIVE_NAME).exists()


def test_corrupt_archive_is_removed(tmp_path):
    (tmp_path / ARCHIVE_NAME).write_bytes(gzip.compress(b"\xd0\x9c\xd0\xbe\n" * 1000)[:-20])  # обрезан
    with pytest.raises(RuntimeError, match="archive removed"):
        ensure_index(tmp_path, Lemmatizer(), show_progress=False)
    assert not (tmp_path / ARCHIVE_NAME).exists() and not (tmp_path / DB_NAME).exists()


def test_old_schema_and_garbage_db_are_rebuilt(tmp_path):
    write_dump(tmp_path)
    old = sqlite3.connect(tmp_path / DB_NAME)   # формат 1.2.0: без таблицы meta
    old.execute('CREATE VIRTUAL TABLE titles_fts USING fts5(title, lemmas, tokenize="trigram")')
    old.commit(); old.close()
    assert read_meta(tmp_path / DB_NAME) is None
    ensure_index(tmp_path, Lemmatizer(), show_progress=False)
    assert read_meta(tmp_path / DB_NAME) is not None

    (tmp_path / DB_NAME).write_bytes(b"this is not sqlite" * 100)
    write_dump(tmp_path)
    assert read_meta(tmp_path / DB_NAME) is None
    ensure_index(tmp_path, Lemmatizer(), show_progress=False)
    assert read_meta(tmp_path / DB_NAME) is not None


def test_download_requires_user_agent(tmp_path):
    with pytest.raises(ValueError, match="user_agent"):
        ensure_index(tmp_path, Lemmatizer(), show_progress=False)


def test_concurrent_start_builds_once(tmp_path, monkeypatch):
    write_dump(tmp_path)
    real, count = index_builder.build_index, {"n": 0}

    def slow(*a, **k):
        count["n"] += 1
        time.sleep(0.4)
        return real(*a, **k)

    monkeypatch.setattr(index_builder, "build_index", slow)
    errors = []

    def run():
        try:
            ensure_index(tmp_path, Lemmatizer(), show_progress=False)
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=run) for _ in range(3)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert not errors and count["n"] == 1


PAYLOAD = gzip.compress("\n".join(TITLES).encode())


def serve(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/dump.gz"


class Good(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.send_header("Last-Modified", "Tue, 02 Jun 2026 03:04:05 GMT")
        self.end_headers()
        self.wfile.write(PAYLOAD)

    def log_message(self, *a): pass


class Truncated(Good):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()
        self.wfile.write(PAYLOAD[: len(PAYLOAD) // 2])  # и закрываем соединение


class NotFound(Good):
    def do_GET(self):
        self.send_response(404); self.end_headers()


def test_download_ok(tmp_path):
    server, url = serve(Good)
    dest = tmp_path / "d.gz"
    download_dump(requests.Session(), url, dest, show_progress=False)
    server.shutdown()
    assert dest.read_bytes() == PAYLOAD and not (tmp_path / "d.gz.part").exists()
    assert time.gmtime(dest.stat().st_mtime)[:3] == (2026, 6, 2)  # дата дампа из Last-Modified


@pytest.mark.parametrize("handler", [Truncated, NotFound])
def test_download_failure_leaves_no_files(tmp_path, monkeypatch, handler):
    monkeypatch.setattr(index_builder.time, "sleep", lambda s: None)
    server, url = serve(handler)
    dest = tmp_path / "d.gz"
    with pytest.raises(RuntimeError, match="Failed to download"):
        download_dump(requests.Session(), url, dest, attempts=2, show_progress=False)
    server.shutdown()
    assert not dest.exists() and not (tmp_path / "d.gz.part").exists()


def test_full_flow_download_then_build(tmp_path):
    server, url = serve(Good)
    with WikiTitleFinder("test-agent", tmp_path, dump_url=url, show_progress=False) as f:
        assert f.find("Рим")[0] == "Рим"
        assert f.info()["dump_last_modified"].startswith("2026-06-02")
    server.shutdown()
