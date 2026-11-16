"""Нормализация названий и извлечение характеристик (количество, процент)."""
from __future__ import annotations

import re

import numpy as np

_QTY_RE = re.compile(r"(?:(\d+)\s*[xх]\s*)?(\d+(?:\.\d+)?)\s*(кг|г|мл|л|шт)\b")
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def normalize(s: str) -> str:
    """Нижний регистр, «ё» -> «е», десятичная запятая -> точка, без пунктуации."""
    s = s.lower().replace("ё", "е")
    s = re.sub(r"(\d),(\d)", r"\1.\2", s)
    return " ".join(re.sub(r"[^\w\s.%]", " ", s).split())


def parse_qty(text: str):
    """Возвращает (количество в г / мл / шт, базовая единица) или (None, None)."""
    t = normalize(text.replace("×", "x"))
    m = _QTY_RE.search(t)
    if not m:
        return None, None
    count = int(m.group(1)) if m.group(1) else 1
    value, unit = float(m.group(2)) * count, m.group(3)
    factor, base = {"кг": (1000, "г"), "л": (1000, "мл")}.get(unit, (1, unit))
    return value * factor, base


def parse_percent(text: str):
    m = _PERCENT_RE.search(normalize(text))
    return float(m.group(1)) if m else None


def attrs_compatible(a: str, b: str) -> bool:
    """False, если у обоих товаров указан процент или количество и они не совпадают."""
    pa, pb = parse_percent(a), parse_percent(b)
    if pa is not None and pb is not None and pa != pb:
        return False
    qa, ua = parse_qty(a)
    qb, ub = parse_qty(b)
    if qa is not None and qb is not None and (ua != ub or not np.isclose(qa, qb)):
        return False
    return True
