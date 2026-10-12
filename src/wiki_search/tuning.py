"""
Подбор весов формулы ранжирования по метрике NDCG@k.

    pip install "ru-wiki-search[tune]"
    python -m wiki_search.tuning --benchmark benchmarks/seed.jsonl --output ranking.json

Можно передать несколько файлов: --benchmark seed.jsonl generated.jsonl (склеивать не нужно).

Формат бенчмарка — JSONL, по строке на запрос (пустые строки и строки с «#» пропускаются)::

    {"query": "Великого шелкового пути", "relevant": {"Великий шёлковый путь": 3, "Шёлковый путь": 1}}
    {"query": "москве", "relevant": ["Москва"]}

«relevant» — словарь «заголовок → градация релевантности» (целое > 0, больше = лучше) либо
список заголовков (все с градацией 1). Заголовки сравниваются без учёта регистра и ё/е.

Как это работает: кандидаты из индекса и признаки пар «запрос — заголовок» не зависят от
весов, поэтому считаются один раз; дальше Optuna перебирает веса, а скор и NDCG считаются
векторно. Бенчмарк делится на обучающую и валидационную части, выигрыш оценивается на
валидационной — так видно, не переобучились ли веса на маленьком наборе.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .internal import PROJECT_NAME, PROJECT_VERSION, RankingConfig, WikiTitleFinder, is_valid_email
from .internal.text import collapse_spaces, normalize_text

FEATURE_COLUMNS = 6  # sim_raw, sim_lemma, exact, exact_lemma, has_brackets, len_diff

# Диапазоны поиска. w_sim не подбирается: это общий масштаб (см. RankingConfig).
SEARCH_SPACE: dict[str, tuple[float, float]] = {
    "w_raw_ratio": (0.0, 1.0),
    "exact_bonus": (0.0, 2.0),
    "exact_lemma_ratio": (0.0, 1.0),
    "brackets_penalty": (0.5, 1.0),
    "w_len_penalty": (0.0, 0.05),
}


def title_key(title: str) -> str:
    return collapse_spaces(normalize_text(title))


# ---------------------------------------------------------------------------
# Бенчмарк и метрика (без внешних зависимостей)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BenchmarkItem:
    query: str
    relevant: dict[str, float]  # заголовок -> градация релевантности


def load_benchmark(path: str | Path) -> list[BenchmarkItem]:
    items: list[BenchmarkItem] = []
    with open(path, encoding="utf-8-sig") as f:  # utf-8-sig: файл из Блокнота/PowerShell с BOM тоже читается
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                raw = json.loads(line)
                query = str(raw["query"]).strip()
                rel = raw["relevant"]
                if isinstance(rel, list):
                    rel = {t: 1 for t in rel}
                relevant = {str(t): float(g) for t, g in rel.items()}
                if not query or not relevant or any(g <= 0 for g in relevant.values()):
                    raise ValueError("empty query/relevant or non-positive grade")
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                raise ValueError(f"{path}:{n}: bad benchmark line ({e})") from e
            items.append(BenchmarkItem(query, relevant))
    return items


def load_benchmarks(paths: Sequence[str | Path]) -> list[BenchmarkItem]:
    """Загружает несколько файлов; одинаковые запросы объединяются (берётся наибольшая градация)."""
    merged: dict[str, BenchmarkItem] = {}
    for path in paths:
        for item in load_benchmark(path):
            key = item.query.lower()
            if key in merged:
                rel = dict(merged[key].relevant)
                for title, grade in item.relevant.items():
                    rel[title] = max(grade, rel.get(title, 0.0))
                merged[key] = BenchmarkItem(merged[key].query, rel)
            else:
                merged[key] = item
    return list(merged.values())


def write_benchmark(items: Sequence[BenchmarkItem], path: str | Path, header: str = "") -> None:
    with open(path, "w", encoding="utf-8") as f:
        for line in header.splitlines():
            f.write(f"# {line}\n")
        for item in items:
            f.write(json.dumps({"query": item.query, "relevant": item.relevant}, ensure_ascii=False) + "\n")


def _gain(grade: float) -> float:
    return 2.0 ** grade - 1.0


def dcg(gains: Sequence[float]) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at_k(ranked: Sequence[str], relevant: Mapping[str, float], k: int) -> float:
    """
    NDCG@k с градациями: gain = 2^grade - 1, дисконт 1/log2(позиция + 1).
    Идеальный порядок строится по ВСЕМ релевантным заголовкам, даже если их нет в выдаче.
    Два заголовка с одним ключом (Шёлковый/Шелковый) засчитываются один раз.
    :return: значение 0..1; 0.0, если релевантных нет.
    """
    rel = {title_key(t): g for t, g in relevant.items()}
    ideal = dcg(sorted((_gain(g) for g in rel.values()), reverse=True)[:k])
    if ideal == 0:
        return 0.0
    seen: set[str] = set()
    gains: list[float] = []
    for title in ranked[:k]:
        key = title_key(title)
        if key in rel and key not in seen:
            seen.add(key)
            gains.append(_gain(rel[key]))
        else:
            gains.append(0.0)
    return dcg(gains) / ideal


# ---------------------------------------------------------------------------
# Векторная оценка (нужен numpy)
# ---------------------------------------------------------------------------

def _np():
    try:
        import numpy as np
    except ImportError as e:  # pragma: no cover
        raise RuntimeError('numpy is required: pip install "ru-wiki-search[tune]"') from e
    return np


@dataclass
class QueryData:
    query: str
    features: "object"        # ndarray (n, 6)
    gains: "object"           # ndarray (n,): gain кандидата, 0 если не релевантен
    group: "object"           # ndarray (n,): номер релевантного ключа или -1
    ideal_dcg: float
    dup_possible: bool        # среди кандидатов есть два с одним релевантным ключом
    relevant_total: int
    relevant_found: int       # сколько релевантных ключей вообще попало в кандидаты


@dataclass(frozen=True)
class Metrics:
    ndcg: float
    hit_at_1: float
    queries: int


def build_query_data(
    query: str, relevant: Mapping[str, float],
    rows_features: Sequence[Sequence[float]], titles: Sequence[str], k: int,
) -> QueryData | None:
    np = _np()
    rel = {title_key(t): g for t, g in relevant.items()}
    ideal = dcg(sorted((_gain(g) for g in rel.values()), reverse=True)[:k])
    if ideal == 0:
        return None
    index = {key: i for i, key in enumerate(rel)}
    n = len(titles)
    gains = np.zeros(n)
    group = np.full(n, -1, dtype=int)
    for i, title in enumerate(titles):
        key = title_key(title)
        if key in rel:
            gains[i] = _gain(rel[key])
            group[i] = index[key]
    found = group[group >= 0]
    return QueryData(
        query=query,
        features=np.asarray(rows_features, dtype=float).reshape(n, FEATURE_COLUMNS),
        gains=gains, group=group, ideal_dcg=ideal,
        dup_possible=len(found) != len(set(found.tolist())),
        relevant_total=len(rel), relevant_found=len(set(found.tolist())),
    )


def build_dataset(
    finder: WikiTitleFinder, items: Sequence[BenchmarkItem], k: int, *, progress: bool = True,
) -> list[QueryData]:
    from tqdm import tqdm
    data: list[QueryData] = []
    for item in tqdm(items, desc="Collecting candidates", disable=not progress):
        cands = finder.candidates(item.query)
        qd = build_query_data(
            item.query, item.relevant,
            [f.as_row() for f in finder.features(cands)],
            [title for title, _ in cands.rows], k,
        )
        if qd is not None:
            data.append(qd)
    return data


def _scores(features, cfg: RankingConfig):
    """Векторный аналог scoring.combine (те же операции в том же порядке)."""
    np = _np()
    sim_raw, sim_lemma, exact, exact_lemma, brackets, len_diff = features.T
    sim = cfg.w_raw_ratio * sim_raw + (1.0 - cfg.w_raw_ratio) * sim_lemma
    score = sim * cfg.w_sim * np.where(brackets > 0, cfg.brackets_penalty, 1.0)
    bonus = np.where(exact > 0, cfg.exact_bonus,
                     np.where(exact_lemma > 0, cfg.exact_bonus * cfg.exact_lemma_ratio, 0.0))
    return score + bonus - len_diff * cfg.w_len_penalty


def evaluate(data: Sequence[QueryData], cfg: RankingConfig, k: int) -> Metrics:
    np = _np()
    if not data:
        return Metrics(0.0, 0.0, 0)
    discounts = 1.0 / np.log2(np.arange(2, k + 2))
    total = hits = 0.0
    for qd in data:
        order = np.argsort(-_scores(qd.features, cfg), kind="stable")[:k]  # как sorted(reverse=True)
        gains = qd.gains[order].copy()
        if qd.dup_possible:
            seen: set[int] = set()
            for i, idx in enumerate(order):
                grp = int(qd.group[idx])
                if grp >= 0:
                    if grp in seen:
                        gains[i] = 0.0
                    seen.add(grp)
        total += float((gains * discounts[:len(gains)]).sum()) / qd.ideal_dcg
        hits += 1.0 if len(gains) and gains[0] > 0 else 0.0
    return Metrics(total / len(data), hits / len(data), len(data))


# ---------------------------------------------------------------------------
# Подбор
# ---------------------------------------------------------------------------

def split_dataset(
    data: Sequence[QueryData], val_fraction: float, seed: int
) -> tuple[list[QueryData], list[QueryData]]:
    data = list(data)
    if val_fraction <= 0 or len(data) < 4:
        return data, []
    rng = random.Random(seed)
    rng.shuffle(data)
    n_val = min(max(1, round(len(data) * val_fraction)), len(data) - 1)
    return data[n_val:], data[:n_val]


def tune(
    train: Sequence[QueryData], k: int, *, base: RankingConfig | None = None,
    n_trials: int = 300, seed: int = 0, show_progress: bool = False,
) -> RankingConfig:
    """
    Максимизирует средний NDCG@k на ``train`` (Optuna TPE). Первым пробуется ``base``,
    поэтому результат на ``train`` не бывает хуже исходного.
    """
    try:
        import optuna
    except ImportError as e:  # pragma: no cover
        raise RuntimeError('optuna is required: pip install "ru-wiki-search[tune]"') from e
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    base = base or RankingConfig()

    def make(params: Mapping[str, float]) -> RankingConfig:
        return RankingConfig(w_sim=base.w_sim, **params)

    def objective(trial: "optuna.Trial") -> float:
        params = {name: trial.suggest_float(name, lo, hi) for name, (lo, hi) in SEARCH_SPACE.items()}
        return evaluate(train, make(params), k).ndcg

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.enqueue_trial({
        name: min(max(getattr(base, name), lo), hi) for name, (lo, hi) in SEARCH_SPACE.items()
    })
    study.optimize(objective, n_trials=n_trials, show_progress_bar=show_progress)
    return make(study.best_params)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _fmt(m: Metrics) -> str:
    return f"NDCG={m.ndcg:.4f}  Hit@1={m.hit_at_1:.3f}  (n={m.queries})" if m.queries else "—"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wiki_search.tuning", description=__doc__.split("\n\n")[0])
    ap.add_argument("--benchmark", required=True, nargs="+", metavar="FILE",
                    help="один или несколько JSONL-файлов с запросами и ожидаемыми заголовками")
    ap.add_argument("--data-dir", help="каталог индекса (по умолчанию — как у WikiSearcher)")
    ap.add_argument("--email", help="e-mail для User-Agent (нужен только если индекса ещё нет)")
    ap.add_argument("--user-agent", help="свой User-Agent вместо e-mail")
    ap.add_argument("--base", help="JSON с исходными весами (по умолчанию — встроенные)")
    ap.add_argument("--k", type=int, default=5, help="глубина NDCG@k (по умолчанию 5)")
    ap.add_argument("--trials", type=int, default=300, help="число проб Optuna")
    ap.add_argument("--val-fraction", type=float, default=0.3, help="доля валидационных запросов (0 — не делить)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--output", default="ranking.json", help="куда сохранить подобранные веса")
    ap.add_argument("--report", help="сохранить отчёт (метрики и веса) в JSON")
    ap.add_argument("--write-pruned", metavar="PATH",
                    help="записать бенчмарк без заголовков, которых нет в индексе, и выйти")
    ap.add_argument("--evaluate-only", action="store_true", help="только оценить текущие веса")
    ap.add_argument("--force", action="store_true", help="сохранить веса, даже если на валидации стало не лучше")
    args = ap.parse_args(argv)

    user_agent = args.user_agent
    if not user_agent and args.email:
        if not is_valid_email(args.email):
            ap.error(f"'{args.email}' is not a valid email address")
        user_agent = f"{PROJECT_NAME}/{PROJECT_VERSION} (tuning; {args.email})"

    base = RankingConfig.load(args.base) if args.base else RankingConfig()
    items = load_benchmarks(args.benchmark)
    if not items:
        ap.error("benchmark is empty")

    with WikiTitleFinder(user_agent, args.data_dir, ranking=base) as finder:
        present: dict[str, bool] = {}

        def exists(title: str) -> bool:
            if title not in present:
                present[title] = finder.has_title(title)
            return present[title]

        missing = [(it.query, t) for it in items for t in it.relevant if not exists(t)]

        if args.write_pruned:
            kept = [BenchmarkItem(it.query, {t: g for t, g in it.relevant.items() if exists(t)})
                    for it in items]
            kept = [it for it in kept if it.relevant]
            write_benchmark(kept, args.write_pruned,
                            f"Очищено от заголовков, которых нет в индексе. Исходные файлы: {', '.join(args.benchmark)}")
            removed = sorted({t for _, t in missing})
            print(f"Оставлено запросов: {len(kept)} из {len(items)}; "
                  f"убрано заголовков: {len(removed)} -> {args.write_pruned}")
            if removed:
                print("Убранные заголовки (просмотрите: возможны ошибки в написании, а не отсутствие статьи):")
                for title in removed:
                    print(f"  {title}")
            return 0

        if missing:
            print(f"\nОжидаемых заголовков нет в индексе: {len(missing)} — проверьте бенчмарк "
                  f"или очистите его флагом --write-pruned, например:", file=sys.stderr)
            for query, title in missing[:15]:
                print(f"  {query!r} -> {title!r}", file=sys.stderr)
        data = build_dataset(finder, items, args.k)

    if not data:
        print("Нет ни одного запроса с релевантным заголовком в индексе.", file=sys.stderr)
        return 1
    found = sum(1 for d in data if d.relevant_found > 0)
    print(f"\nЗапросов в оценке: {len(data)} из {len(items)}; "
          f"релевантный заголовок попал в кандидаты у {found} ({found / len(data):.0%}) "
          f"— это потолок для любых весов.")
    if len(data) < 50:
        print("ВНИМАНИЕ: меньше 50 запросов — веса легко переобучить, ориентируйтесь на валидацию.")

    train, val = split_dataset(data, args.val_fraction, args.seed)
    base_train, base_val = evaluate(train, base, args.k), evaluate(val, base, args.k)
    print(f"\nИсходные веса  train: {_fmt(base_train)}\n               val:   {_fmt(base_val)}")
    if args.evaluate_only:
        return 0

    tuned = tune(train, args.k, base=base, n_trials=args.trials, seed=args.seed, show_progress=True)
    tuned_train, tuned_val = evaluate(train, tuned, args.k), evaluate(val, tuned, args.k)
    print(f"\nПодобранные    train: {_fmt(tuned_train)}\n               val:   {_fmt(tuned_val)}")
    for name, value in tuned.to_dict().items():
        print(f"  {name:18s} {getattr(base, name):9.4f} -> {value:9.4f}")

    improved = (not val) or tuned_val.ndcg >= base_val.ndcg + 1e-9
    if args.report:
        Path(args.report).write_text(json.dumps({
            "k": args.k, "base": base.to_dict(), "tuned": tuned.to_dict(),
            "base_train": base_train.__dict__, "base_val": base_val.__dict__,
            "tuned_train": tuned_train.__dict__, "tuned_val": tuned_val.__dict__,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if improved or args.force:
        tuned.save(args.output)
        print(f"\nВеса сохранены в {args.output}. Использование: "
              f"WikiSearcher(..., ranking=RankingConfig.load({args.output!r}))")
    else:
        print("\nНа валидации лучше не стало — веса НЕ сохранены (--force, чтобы сохранить). "
              "Скорее всего, текущих запросов мало или встроенные веса уже хороши.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
