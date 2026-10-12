import pytest


def test_inflected_query(finder):
    assert finder.find("Великого шелкового пути")[0] == "Великий шёлковый путь"
    assert finder.find("чёрных дыр")[0] == "Чёрная дыра"
    assert finder.find("теории относительности")[0] == "Теория относительности"


def test_yo_ye_insensitive(finder):
    assert "Шёлковый путь" in finder.find("шелковый путь")
    assert finder.find("елка")[0] in {"Ёлка", "Ель"}


def test_short_word_does_not_zero_the_strict_query(finder):
    cands = finder.candidates("Москва и Санкт-Петербург")
    assert [t for t, _ in cands.rows] == ["Москва — Санкт-Петербург"]


def test_titles_shorter_than_three_chars(finder):
    assert finder.find("ИИ") == ["ИИ"]
    assert sorted(finder.find("ра")) == ["РА", "Ра"]
    assert finder.find("ии в рф")[0] == "ИИ в РФ"
    assert finder.find("Wi-Fi")[0] == "Wi-Fi"


def test_latin_titles(finder):
    assert finder.find("Python")[0] == "Python"
    assert finder.find("skype")[0] == "Скайп (Skype)"
    assert finder.find("iphone")[0] == "iPhone"


def test_case_twins_are_both_kept(finder):
    assert finder.has_title("МИР") and finder.has_title("Мир")
    assert {"Мир", "МИР"} <= set(finder.find("мир", 5))


def test_exact_match_beats_bracketed(finder):
    assert finder.find("Москва")[0] == "Москва"
    assert finder.find("Волга")[0] == "Волга"


def test_has_title(finder):
    assert finder.has_title("великий шелковый путь") and finder.has_title("ии") and finder.has_title("Wi-Fi")
    assert finder.has_title("Чёрная дыра") and finder.has_title("чёрное море") and finder.has_title("черная дыра")
    assert finder.has_title("Достоевский, Фёдор Михайлович") and finder.has_title("достоевский, федор михайлович")
    assert not finder.has_title("Чёрная") and not finder.has_title("!!!")
    assert not finder.has_title("Несуществующая статья") and not finder.has_title("Яя")


@pytest.mark.parametrize("q", ["", "   ", "!!!", "\"", "'; DROP TABLE titles_fts;--", '"Мир"', "мир AND OR NOT", "*", "(("])
def test_weird_queries_do_not_crash(finder, q):
    assert isinstance(finder.find(q), list)


def test_empty_queries_return_nothing(finder):
    assert finder.find("") == [] and finder.find("!!!") == []


def test_info(finder):
    info = finder.info()
    assert info["schema_version"] == "2" and int(info["row_count"]) > 20
    assert info["dump_last_modified"] and info["built_at"]


def test_index_opened_read_only(finder):
    import sqlite3
    with pytest.raises(sqlite3.OperationalError):
        finder._conn.execute("DELETE FROM meta")
