#
# scoring.py
#

from rapidfuzz import fuzz


def _get_similarity_score(text1: str, text2: str) -> float:
    return fuzz.token_sort_ratio(text1, text2) / 100.0


def calculate_score(
    query: str,
    title: str,
    query_lemmas: str,
    title_lemmas: str,
    w_sim: float,
    w_raw_ratio: float,
    exact_bonus: float,
    exact_lemma_ratio: float,
    brackets_penalty: float,
    w_len_penalty: float,
) -> float:
    """ INTERNAL FUNCTION! """
    q_clean = query.strip().lower()
    t_clean = title.strip().lower()
    sim_raw = _get_similarity_score(q_clean, t_clean)
    sim_lemma = (
        _get_similarity_score(query_lemmas, title_lemmas)
        if (query_lemmas and title_lemmas) else sim_raw
    )
    sim = (w_raw_ratio * sim_raw) + ((1.0 - w_raw_ratio) * sim_lemma)
    bracket_mult = brackets_penalty if ("(" in title or ")" in title) else 1.0
    score = (sim * w_sim) * bracket_mult
    if q_clean == t_clean:
        score += exact_bonus
    elif query_lemmas and query_lemmas == title_lemmas:
        score += exact_bonus * exact_lemma_ratio
    len_diff = abs(len(t_clean) - len(q_clean))
    score -= len_diff * w_len_penalty
    return score
