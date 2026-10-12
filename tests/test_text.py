from wiki_search.internal.text import make_summary, remove_parenthesized, split_sentences


def test_century_and_bc_abbreviations_do_not_split():
    text = "Дорога существовала со II в. до н. э. по XV в. Связывала Восток и Запад."
    assert len(split_sentences(text)) == 1  # консервативно: после «в.» не режем


def test_geographic_abbreviations_and_initials():
    text = "Город на р. Волга, в 200 км от г. Москвы. Население 100 тыс. чел. А. С. Пушкин родился в 1799. Потом жил."
    parts = split_sentences(text)
    assert parts[0] == "Город на р. Волга, в 200 км от г. Москвы."
    assert "А. С. Пушкин родился в 1799." in parts
    assert parts[-1] == "Потом жил."


def test_question_exclamation_and_lowercase_continuation():
    assert split_sentences("Что это? Это тест! Да.") == ["Что это?", "Это тест!", "Да."]
    assert split_sentences("Он сказал это. и ушёл.") == ["Он сказал это. и ушёл."]


def test_closing_quote_stays_with_sentence():
    assert split_sentences("Он сказал «да». Потом ушёл.")[0] == "Он сказал «да»."


def test_remove_parenthesized():
    assert remove_parenthesized("Пушкин (род. в Москве (Россия) в 1799) — поэт") == "Пушкин — поэт"
    assert remove_parenthesized("Москва (рус.), столица") == "Москва, столица"
    assert remove_parenthesized("(Привет) мир") == "мир"
    # незакрытая скобка остаётся, закрытая внутри неё удаляется
    assert remove_parenthesized("a (b (c) d") == "a (b d"
    assert remove_parenthesized("без скобок") == "без скобок"


def test_unbalanced_pathological_input_is_fast():
    import time
    t = time.time()
    remove_parenthesized("(" + "слово " * 50_000)
    assert time.time() - t < 2


def test_summary_ellipsis_only_when_truncated():
    assert make_summary("Москва — столица России.") == "Москва — столица России."
    assert make_summary("Раз. Два. Три.") == "Раз. Два..."
    assert make_summary("Раз. Два.", max_sentences=2) == "Раз. Два."


def test_summary_cleanup_and_limits():
    assert make_summary("Мо\u0301сква (рус.) — город.") == "Москва — город."
    assert make_summary("Один два три четыре пять шесть семь.", max_chars=15) == "Один два три..."
    assert make_summary("Слово", max_chars=3) == "Сло..."  # длинное слово режется как есть
    assert make_summary(None) is None and make_summary("   ") is None and make_summary("(только скобки)") is None
