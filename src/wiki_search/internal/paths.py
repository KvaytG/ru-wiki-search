#
# paths.py
#
from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_cache_dir

ENV_DATA_DIR = "RU_WIKI_SEARCH_DATA_DIR"


def resolve_data_dir(data_dir: str | os.PathLike | None = None) -> Path:
    if data_dir is not None:
        return Path(data_dir).expanduser()
    env = os.environ.get(ENV_DATA_DIR)
    if env:
        return Path(env).expanduser()
    return Path(user_cache_dir("ru-wiki-search", appauthor=False))
