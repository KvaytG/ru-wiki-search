import json
import math
import random

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("optuna")

from wiki_search import RankingConfig
from wiki_search import tuning
from wiki_search.tuning import (
    BenchmarkItem, build_dataset, build_query_data, evaluate, load_benchmark, load_benchmarks, ndcg_at_k,
    split_dataset, tune,
)


def test_ndcg_binary():
    assert ndcg_at_k(["A", "B", "C"], {"B": 1}, 3) == pytest.approx(1 / math.log2(3))
    assert ndcg_at_k(["B", "A"], {"B": 1}, 3) == pytest.approx(1.0)
    assert ndcg_at_k(["A", "C"], {"B": 1}, 3) == 0.0
    assert ndcg_at_k(["B"], {}, 3) == 0.0            # нет релевантных


def test_ndcg_graded_and_ideal_counts_missing_docs():
    ranked, rel = ["B", "A"], {"A": 3, "B": 1}
    dcg = 1 / 1 + 7 / math.log2(3)
    ideal = 7 / 1 + 1 / math.log2(3)
    assert ndcg_at_k(ranked, rel, 5) == pytest.approx(dcg / ideal)
    # релевантный документ, которого нет в выдаче, всё равно входит в идеал
    assert ndcg_at_k(["A"], rel, 5) == pytest.approx(7 / ideal)


def test_ndcg_k_cutoff_and_yo_dedup():
    assert ndcg_at_k(["X", "Y", "A"], {"A": 1}, 2) == 0.0
    assert ndcg_at_k(["Шёлк", "Шелк"], {"шелк": 1}, 5) == pytest.approx(1.0)


def test_load_benchmark(tmp_path):
    p = tmp_path / "b.jsonl"
    p.write_text('# комментарий\n\n{"query": " Рим ", "relevant": ["Рим"]}\n'
                 '{"query": "мир", "relevant": {"Мир": 3, "МИР": 1}}\n', encoding="utf-8")
    items = load_benchmark(p)
    assert items == [BenchmarkItem("Рим", {"Рим": 1.0}), BenchmarkItem("мир", {"Мир": 3.0, "МИР": 1.0})]
    for bad in ['{"query": "x"}', '{"query": "x", "relevant": {"A": 0}}', "not json", '{"query": "", "relevant": ["A"]}']:
        p.write_text(bad + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match=r"b\.jsonl:1"):
            load_benchmark(p)


ITEMS = [
    BenchmarkItem("Великого шелкового пути", {"Великий шёлковый путь": 3, "Шёлковый путь": 1}),
    BenchmarkItem("москве", {"Москва": 3, "Москва (значения)": 1}),
    BenchmarkItem("мир", {"Мир": 3, "МИР": 2}),
    BenchmarkItem("пушкин", {"Пушкин, Александр Сергеевич": 3, "Пушкин (город)": 1}),
    BenchmarkItem("Волга", {"Волга": 3}),
    BenchmarkItem("ии", {"ИИ": 3}),
    BenchmarkItem("Python", {"Python": 3}),
    BenchmarkItem("черная дыра", {"Чёрная дыра": 3}),
]
K = 5


def random_configs(n=12, seed=1):
    rng = random.Random(seed)
    yield RankingConfig()
    for _ in range(n):
        yield RankingConfig(
            w_sim=rng.uniform(0.5, 3), w_raw_ratio=rng.random(), exact_bonus=rng.uniform(0, 2),
            exact_lemma_ratio=rng.random(), brackets_penalty=rng.uniform(0.5, 1), w_len_penalty=rng.uniform(0, 0.05))


def test_vectorized_evaluation_matches_production_find(index_dir):
    from wiki_search.internal import WikiTitleFinder
    with WikiTitleFinder(data_dir=index_dir, show_progress=False) as finder:
        data = build_dataset(finder, ITEMS, K, progress=False)
        assert len(data) == len(ITEMS)
        for cfg in random_configs():
            finder._ranking = cfg
            expected = sum(ndcg_at_k(finder.find(it.query, K), it.relevant, K) for it in ITEMS) / len(ITEMS)
            assert evaluate(data, cfg, K).ndcg == pytest.approx(expected, abs=1e-12), cfg


def test_hit_at_1_and_recall_stats(index_dir):
    from wiki_search.internal import WikiTitleFinder
    with WikiTitleFinder(data_dir=index_dir, show_progress=False) as finder:
        data = build_dataset(finder, ITEMS, K, progress=False)
    m = evaluate(data, RankingConfig(), K)
    assert 0 < m.hit_at_1 <= 1 and m.queries == len(ITEMS)
    assert all(d.relevant_found >= 1 for d in data)


def crafted(n=20):
    feats = [(0.90, 0.90, 0, 0, 0, 0),    # A
             (0.85, 0.85, 0, 1, 0, 0)]    # B
    out = []
    for i in range(n):
        qd = build_query_data(f"q{i}", {"B": 3}, feats, ["A", "B"], K)
        out.append(qd)
    return out


def test_baseline_is_wrong_and_tuning_fixes_it():
    data = crafted()
    base = evaluate(data, RankingConfig(), K)
    assert base.hit_at_1 == 0.0
    tuned_cfg = tune(data, K, n_trials=80, seed=0)
    tuned = evaluate(data, tuned_cfg, K)
    assert tuned.ndcg > base.ndcg and tuned.hit_at_1 == 1.0
    assert tuned_cfg.w_sim == RankingConfig().w_sim
    for name, (lo, hi) in tuning.SEARCH_SPACE.items():
        assert lo <= getattr(tuned_cfg, name) <= hi


def test_tuning_never_worse_than_baseline_on_train():
    feats = [(0.5, 0.5, 1, 1, 0, 0), (0.9, 0.9, 0, 0, 0, 0)]
    data = [build_query_data("q", {"A": 3}, feats, ["A", "B"], K)]
    base = evaluate(data, RankingConfig(), K).ndcg
    assert evaluate(data, tune(data, K, n_trials=15, seed=3), K).ndcg >= base


def test_split_is_reproducible_and_disjoint():
    data = crafted(10)
    a1, b1 = split_dataset(data, 0.3, seed=7)
    a2, b2 = split_dataset(data, 0.3, seed=7)
    assert [d.query for d in b1] == [d.query for d in b2] and len(b1) == 3 and len(a1) == 7
    assert not {d.query for d in a1} & {d.query for d in b1}
    assert split_dataset(data, 0, 0) == (data, []) and split_dataset(data[:3], 0.5, 0)[1] == []


def test_ranking_config_roundtrip(tmp_path):
    cfg = RankingConfig(exact_bonus=0.5)
    cfg.save(tmp_path / "r.json")
    assert RankingConfig.load(tmp_path / "r.json") == cfg
    (tmp_path / "w.json").write_text(json.dumps({"ranking": {"exact_bonus": 0.1}}))
    assert RankingConfig.load(tmp_path / "w.json").exact_bonus == 0.1
    with pytest.raises(ValueError, match="Unknown"):
        RankingConfig.from_dict({"bogus": 1})


def test_cli_end_to_end(index_dir, tmp_path, capsys):
    bench = tmp_path / "b.jsonl"
    bench.write_text("\n".join(json.dumps({"query": i.query, "relevant": i.relevant}, ensure_ascii=False) for i in ITEMS)
                     + '\n{"query": "нет", "relevant": ["Такой статьи нет в индексе"]}\n', encoding="utf-8")
    out, report = tmp_path / "ranking.json", tmp_path / "report.json"
    code = tuning.main(["--benchmark", str(bench), "--data-dir", str(index_dir), "--k", "5", "--trials", "10",
                        "--val-fraction", "0", "--output", str(out), "--report", str(report)])
    captured = capsys.readouterr()
    assert code == 0
    assert "Такой статьи нет в индексе" in captured.err
    assert RankingConfig.load(out)
    rep = json.loads(report.read_text())
    assert rep["tuned_train"]["ndcg"] >= rep["base_train"]["ndcg"]

    code = tuning.main(["--benchmark", str(bench), "--data-dir", str(index_dir), "--evaluate-only"])
    assert code == 0 and "Исходные веса" in capsys.readouterr().out


@pytest.mark.parametrize("val_after,extra,saved", [
    (0.70, [], False),
    (0.70, ["--force"], True),
    (0.90, [], True),
])
def test_cli_saves_only_if_validation_improves(index_dir, tmp_path, monkeypatch, capsys, val_after, extra, saved):
    bench = tmp_path / "b.jsonl"
    bench.write_text("\n".join(json.dumps({"query": i.query, "relevant": i.relevant}, ensure_ascii=False) for i in ITEMS) + "\n", encoding="utf-8")
    M = tuning.Metrics
    # порядок вызовов evaluate в main: base/train, base/val, tuned/train, tuned/val
    answers = iter([M(0.5, 0.5, 5), M(0.8, 0.5, 3), M(0.9, 0.6, 5), M(val_after, 0.5, 3)])
    monkeypatch.setattr(tuning, "evaluate", lambda *a, **k: next(answers))
    monkeypatch.setattr(tuning, "tune", lambda *a, **k: RankingConfig(exact_bonus=1.0))
    out = tmp_path / "ranking.json"
    code = tuning.main(["--benchmark", str(bench), "--data-dir", str(index_dir), "--output", str(out),
                        "--val-fraction", "0.4", *extra])
    text = capsys.readouterr().out
    assert code == 0 and out.exists() is saved and ("НЕ сохранены" in text) is (not saved)
    if saved:
        assert RankingConfig.load(out).exact_bonus == 1.0


def test_cli_write_pruned_removes_missing_titles_and_exits(index_dir, tmp_path, capsys):
    bench, out = tmp_path / "b.jsonl", tmp_path / "pruned.jsonl"
    rows = [
        {"query": "Рим", "relevant": {"Рим": 3}},
        {"query": "чёрная дыра", "relevant": {"Чёрная дыра": 3, "Выдуманная статья": 1}},
        {"query": "нет", "relevant": {"Совсем выдуманная": 3}},
        {"query": "Достоевский", "relevant": {"Достоевский, Фёдор Михайлович": 3}},
        {"query": "ии", "relevant": {"ИИ": 3}},
    ]
    bench.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    code = tuning.main(["--benchmark", str(bench), "--data-dir", str(index_dir), "--write-pruned", str(out)])
    text = capsys.readouterr().out
    assert code == 0 and "Исходные веса" not in text          # подбор не запускался
    kept = {i.query: i.relevant for i in load_benchmark(out)}
    assert set(kept) == {"Рим", "чёрная дыра", "Достоевский", "ии"}
    assert kept["чёрная дыра"] == {"Чёрная дыра": 3.0}
    assert "Выдуманная статья" in text and "Совсем выдуманная" in text and "Рим" not in text.split("убрано")[1]


def test_benchmark_with_utf8_bom_is_readable(tmp_path):
    p = tmp_path / "bom.jsonl"
    p.write_bytes(b"\xef\xbb\xbf" + '# комментарий\n{"query": "Рим", "relevant": ["Рим"]}\n'.encode("utf-8"))
    assert [i.query for i in load_benchmark(p)] == ["Рим"]
    p.write_bytes(b"\xef\xbb\xbf" + '{"query": "Рим", "relevant": ["Рим"]}\n'.encode("utf-8"))  # BOM перед JSON
    assert [i.query for i in load_benchmark(p)] == ["Рим"]


def test_several_benchmark_files_are_merged(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text('{"query": "Рим", "relevant": {"Рим": 1}}\n{"query": "мир", "relevant": ["Мир"]}\n', encoding="utf-8")
    b.write_text('{"query": "РИМ", "relevant": {"Рим": 3, "Римская империя": 2}}\n{"query": "волга", "relevant": ["Волга"]}\n', encoding="utf-8")
    items = {i.query.lower(): i.relevant for i in load_benchmarks([a, b])}
    assert set(items) == {"рим", "мир", "волга"}
    assert items["рим"] == {"Рим": 3.0, "Римская империя": 2.0}


def test_cli_accepts_several_files(index_dir, tmp_path, capsys):
    a, b, out = tmp_path / "a.jsonl", tmp_path / "b.jsonl", tmp_path / "pruned.jsonl"
    a.write_text('{"query": "Рим", "relevant": ["Рим"]}\n', encoding="utf-8")
    b.write_text('{"query": "Волга", "relevant": ["Волга"]}\n{"query": "нет", "relevant": ["Выдумка"]}\n', encoding="utf-8")
    code = tuning.main(["--benchmark", str(a), str(b), "--data-dir", str(index_dir), "--write-pruned", str(out)])
    assert code == 0 and {i.query for i in load_benchmark(out)} == {"Рим", "Волга"}
