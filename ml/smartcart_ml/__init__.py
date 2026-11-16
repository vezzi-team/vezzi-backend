"""ML-модуль «Умная корзина»: сопоставление товаров, поиск аналогов и поиск по тексту."""
from ._version import __version__
from .matcher import Matcher

__all__ = ["Matcher", "__version__"]
