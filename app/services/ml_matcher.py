"""Подключение ML-модуля команды: поиск товаров и похожесть названий.

Сам модуль написан ML-направлением и лежит в папке ml/ (пакет smartcart_ml).
Как он работает и как оценивалось качество, описано в ml/README.md и ml/EVALUATION.md.
Модулю нужен каталог в виде таблицы из двух колонок: product_id и name.

Модуль строит индекс по названиям в памяти. Снимок каталога после публикации
не меняется, поэтому индекс строится один раз на снимок и пересобирается,
только когда опубликован новый снимок.
"""

import threading

import pandas as pd
from smartcart_ml import Matcher
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CatalogImport, Offer, Product


class _MatcherCache:
    def __init__(self) -> None:
        # Запросы обрабатываются в нескольких потоках: индекс строит только один из них.
        self._lock = threading.Lock()
        self._import_id: int | None = None
        self._matcher: Matcher | None = None

    def get(self, session: Session, catalog_import: CatalogImport) -> Matcher:
        with self._lock:
            if self._matcher is None or self._import_id != catalog_import.id:
                self._matcher = _build_matcher(session, catalog_import.id)
                self._import_id = catalog_import.id
            return self._matcher


_cache = _MatcherCache()


def matcher_for(session: Session, catalog_import: CatalogImport) -> Matcher:
    """Matcher по товарам, которые продаются в этом снимке каталога."""
    return _cache.get(session, catalog_import)


def _build_matcher(session: Session, import_id: int) -> Matcher:
    sold = select(Offer.product_id).where(Offer.import_id == import_id)
    rows = session.execute(
        select(Product.id, Product.name).where(Product.id.in_(sold)).order_by(Product.id)
    ).all()
    catalog = pd.DataFrame(
        {"product_id": [row.id for row in rows], "name": [row.name for row in rows]}
    )
    return Matcher(catalog)
