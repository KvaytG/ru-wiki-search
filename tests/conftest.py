import gzip
from pathlib import Path

import pytest

from wiki_search.internal.index_builder import ARCHIVE_NAME
from wiki_search.internal import WikiTitleFinder

TITLES = [
    "Великий_шёлковый_путь", "Шёлковый_путь", "Шёлк", "Великая_Китайская_стена",
    "Москва", "Москва_(значения)", "Москва_—_Санкт-Петербург", "Санкт-Петербург",
    "Петербург", "Пушкин", "Пушкин_(город)", "Пушкин,_Александр_Сергеевич",
    "Эйнштейн,_Альберт", "Достоевский,_Фёдор_Михайлович", "Рим", "Мир", "МИР", "Мир_(значения)", "Ра", "РА", "ИИ",
    "ИИ_в_РФ", "Python", "Скайп_(Skype)", "iPhone", "Wi-Fi", "Ёлка", "Ель",
    "Чёрное_море", "Чёрная_дыра", "Солнечная_система", "Теория_относительности",
    "漢字", "Страница_с_иероглифом_漢", "Волга", "Волга_(значения)", "Волгоград",
]


def write_dump(directory: Path, titles=TITLES) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ARCHIVE_NAME
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write("\n".join(titles) + "\n")
    return path


@pytest.fixture(scope="session")
def index_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("index")
    write_dump(d)
    with WikiTitleFinder(data_dir=d, show_progress=False):
        pass  # строит индекс
    return d


@pytest.fixture
def finder(index_dir):
    f = WikiTitleFinder(data_dir=index_dir, show_progress=False)
    f.load()
    yield f
    f.close()
