#
# ranking.py
#
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class RankingConfig:
    w_sim: float = 2.1599              # масштаб схожести
    w_raw_ratio: float = 0.3250        # доля схожести «сырых» строк (остальное — леммы)
    exact_bonus: float = 0.3274        # бонус за точное совпадение строки
    exact_lemma_ratio: float = 0.2627  # доля бонуса за совпадение лемм
    brackets_penalty: float = 0.9991   # множитель для заголовков со скобками
    w_len_penalty: float = 0.0         # штраф за разницу длин (за символ)

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RankingConfig":
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"Unknown ranking parameters: {sorted(unknown)}")
        return cls(**{k: float(v) for k, v in data.items()})

    @classmethod
    def load(cls, path: str | Path) -> "RankingConfig":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data.get("ranking", data))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
