import pytest
import requests

from wiki_search.internal import WikiApiError, WikiClient


class Resp:
    def __init__(self, status=200, data=None, bad_json=False):
        self.status_code, self._data, self._bad = status, data, bad_json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._data


class Session:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.urls = resp, exc, []
        self.headers = {}

    def get(self, url, **kw):
        self.urls.append(url)
        if self.exc:
            raise self.exc
        return self.resp

    def close(self): pass


DATA = {
    "type": "standard", "titles": {"canonical": "Великий_шёлковый_путь", "normalized": "Великий шёлковый путь"},
    "extract": "Текст.", "description": "торговый путь",
    "content_urls": {"desktop": {"page": "https://ru.wikipedia.org/wiki/%D0%92"}},
}


def test_summary_parsed_and_title_encoded():
    s = Session(Resp(200, DATA))
    page = WikiClient(s).get_summary("Эйнштейн, Альберт/тест")
    assert s.urls[0].endswith("/%D0%AD%D0%B9%D0%BD%D1%88%D1%82%D0%B5%D0%B9%D0%BD%2C_%D0%90%D0%BB%D1%8C%D0%B1%D0%B5%D1%80%D1%82%2F%D1%82%D0%B5%D1%81%D1%82")
    assert (page.title, page.url, page.extract, page.description, page.is_disambiguation) == (
        "Великий шёлковый путь", "https://ru.wikipedia.org/wiki/%D0%92", "Текст.", "торговый путь", False)


def test_disambiguation_and_missing_fields():
    page = WikiClient(Session(Resp(200, {"type": "disambiguation", "titles": {"canonical": "Мир_(значения)"}}))).get_summary("Мир (значения)")
    assert page.is_disambiguation and page.title == "Мир (значения)" and page.extract == "" and page.description is None
    assert page.url.startswith("https://ru.wikipedia.org/wiki/")


@pytest.mark.parametrize("resp", [Resp(404, {}), Resp(200, {"type": "https://mediawiki.org/wiki/HyperSwitch/errors/not_found"})])
def test_not_found_is_none(resp):
    assert WikiClient(Session(resp)).get_summary("X") is None


@pytest.mark.parametrize("session", [
    Session(Resp(500, {})), Session(Resp(200, bad_json=True)), Session(exc=requests.ConnectionError("down")),
])
def test_failures_raise_wiki_api_error(session):
    with pytest.raises(WikiApiError):
        WikiClient(session).get_summary("X")
