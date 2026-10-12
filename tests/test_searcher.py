import pytest

from test_api import Resp, Session
from wiki_search import SearchResult, WikiApiError, WikiSearcher


class Router(Session):
    def __init__(self, routes):
        super().__init__()
        self.routes = routes

    def get(self, url, **kw):
        from urllib.parse import unquote
        self.urls.append(url)
        key = unquote(url.rsplit("/", 1)[1])
        return self.routes.get(key, Resp(404, {}))


def page(title, extract="Текст (скобки). Второе. Третье."):
    return Resp(200, {"type": "standard", "titles": {"normalized": title}, "extract": extract,
                      "content_urls": {"desktop": {"page": f"https://ru.wikipedia.org/wiki/{title.replace(' ', '_')}"}}})


@pytest.fixture
def make(index_dir):
    def factory(routes, **kw):
        s = Router(routes)
        return WikiSearcher("me@example.com", data_dir=index_dir, session=s, show_progress=False, **kw), s
    return factory


def test_search_returns_canonical_title_and_clean_summary(make):
    searcher, _ = make({"Шёлковый_путь": page("Великий шёлковый путь")})
    r = searcher.search("шелковый путь")
    assert isinstance(r, SearchResult)
    assert r.title == "Великий шёлковый путь" and r.matched_title == "Шёлковый путь"
    assert r.summary == "Текст. Второе..."
    assert r["title"] == r.title and r.get("nope", 1) == 1 and r.as_dict()["url"] == r.url
    with pytest.raises(KeyError):
        r["nope"]


def test_falls_back_to_next_candidate_when_page_is_gone(make):
    searcher, s = make({"Москва_(значения)": page("Москва (значения)")})
    r = searcher.search("Москва")      # лучший кандидат «Москва» удалён (404) -> берём следующего
    assert r is not None and r.matched_title != "Москва" and len(s.urls) >= 2


def test_search_none_when_nothing_found(make):
    searcher, s = make({})
    assert searcher.search("zzzzzz нет такого") is None and searcher.search("  ") is None


def test_search_many_collapses_redirects(make):
    same = page("Великий шёлковый путь")
    searcher, _ = make({"Шёлковый_путь": same, "Великий_шёлковый_путь": same, "Шёлк": page("Шёлк")})
    results = searcher.search_many("шёлк", limit=5)
    titles = [r.title for r in results]
    assert titles.count("Великий шёлковый путь") == 1 and "Шёлк" in titles


def test_suggest_is_offline(make):
    searcher, s = make({})
    assert searcher.suggest("Рим", 3)[0] == "Рим" and s.urls == []


def test_network_error_is_not_swallowed(index_dir):
    import requests
    searcher = WikiSearcher("me@example.com", data_dir=index_dir, session=Session(exc=requests.ConnectionError("x")), show_progress=False)
    with pytest.raises(WikiApiError):
        searcher.search("Рим")


def test_summary_options(make):
    searcher, _ = make({"Рим": page("Рим", "Один. Два. Три.")}, summary_sentences=1, max_summary_chars=None)
    assert searcher.search("Рим").summary == "Один..."


def test_user_agent_and_validation(index_dir):
    with pytest.raises(ValueError):
        WikiSearcher(data_dir=index_dir, load_index=False)
    with pytest.raises(ValueError, match="not a valid email"):
        WikiSearcher("nope", data_dir=index_dir, load_index=False)
    s = WikiSearcher(user_agent="MyApp/1.0 (me@example.com)", data_dir=index_dir, show_progress=False)
    assert s._session.headers["User-Agent"] == "MyApp/1.0 (me@example.com)"
    s.close()
    e = WikiSearcher("me@example.com", data_dir=index_dir, load_index=False)
    assert "me@example.com" in e._session.headers["User-Agent"]


def test_context_manager_and_lazy_load(index_dir):
    with WikiSearcher("me@example.com", data_dir=index_dir, load_index=False, show_progress=False) as s:
        assert s._finder._conn is None
        s.load()
        assert s.index_info()["schema_version"] == "2"
    assert s._finder._conn is None
