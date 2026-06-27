"""Package version metadata."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("trading")
except PackageNotFoundError:
    __version__ = "0.1.0"
