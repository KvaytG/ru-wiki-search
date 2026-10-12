#
# constants.py
#
from importlib.metadata import PackageNotFoundError, version

PROJECT_NAME = "RuWikiSearch"

try:
    PROJECT_VERSION = version("ru-wiki-search")
except PackageNotFoundError:
    PROJECT_VERSION = "0+unknown"
