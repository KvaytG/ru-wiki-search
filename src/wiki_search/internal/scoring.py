#
# scoring.py — признаки пары «запрос — заголовок» и их свёртка в скор
#
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from .ranking import RankingConfig


@dataclass(frozen=True, slots=True)
class Features:
    sim_raw: float        # схожесть сырых строк, 0..1
    sim_lemma: float      # схожесть строк лемм, 0..1
    exact: bool           # строки совпали полностью
    exact_lemma: bool     # совпали леммы
    has_brackets: bool    # в заголовке есть скобка
    len_diff: int         # |len(запрос) - len(заголовок)|

    def as_row(self) -> tuple[float, float, float, float, float, float]:
        return (
            self.sim_raw, self.sim_lemma, float(self.exact),
            float(self.exact_lemma), float(self.has_brackets), float(self.len_diff),
        )


def _sim(a: str, b: str) -> float:
    return fuzz.token_sort_ratio(a, b) / 100.0


def extract_features(
    query_lower: str, query_lemmas: str, title: str, title_lemmas: str
) -> Features:
    t_clean = title.strip().lower()
    sim_raw = _sim(query_lower, t_clean)
    sim_lemma = _sim(query_lemmas, title_lemmas) if (query_lemmas and title_lemmas) else sim_raw
    return Features(
        sim_raw=sim_raw,
        sim_lemma=sim_lemma,
        exact=query_lower == t_clean,
        exact_lemma=bool(query_lemmas) and query_lemmas == title_lemmas,
        has_brackets="(" in title,
        len_diff=abs(len(query_lower) - len(t_clean)),
    )


def combine(f: Features, cfg: RankingConfig) -> float:
    """Итоговый скор: чем выше, тем лучше. Формула идентична прежней calculate_score."""
    sim = cfg.w_raw_ratio * f.sim_raw + (1.0 - cfg.w_raw_ratio) * f.sim_lemma
    score = sim * cfg.w_sim * (cfg.brackets_penalty if f.has_brackets else 1.0)
    if f.exact:
        score += cfg.exact_bonus
    elif f.exact_lemma:
        score += cfg.exact_bonus * cfg.exact_lemma_ratio
    return score - f.len_diff * cfg.w_len_penalty
