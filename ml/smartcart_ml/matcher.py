"""Единый интерфейс модуля: сопоставление каталогов, аналоги, поиск."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

from ._version import __version__
from .text import attrs_compatible, normalize

DEFAULT_CONFIG = Path(__file__).with_name("config.json")
METHODS = {
    "identical": {"tfidf", "semantic", "hybrid"},
    "analogs": {"tfidf", "semantic", "hybrid"},
    "search": {"tfidf", "semantic", "rrf"},
}
SEMANTIC = {"semantic", "hybrid", "rrf"}


def _load_config(config) -> dict:
    if config is None:
        config = DEFAULT_CONFIG
    if isinstance(config, (str, Path)):
        config = json.loads(Path(config).read_text(encoding="utf-8"))
    cfg = {k: v for k, v in config.items() if not k.startswith("_")}
    for scenario, allowed in METHODS.items():
        method = cfg.get(scenario, {}).get("method")
        if method not in allowed:
            raise ValueError(
                f"config[{scenario!r}]['method'] должен быть одним из {sorted(allowed)}, получено {method!r}")
    if "threshold" not in cfg["identical"]:
        raise ValueError("config['identical']['threshold'] обязателен")
    return cfg


class Matcher:
    """Каталог товаров + три сценария.

    catalog: таблица с колонками product_id (уникальный) и name.
    config: путь к json, словарь или None (тогда config.json из пакета).
    """

    def __init__(self, catalog: pd.DataFrame, config: str | Path | dict | None = None):
        self.config = _load_config(config)
        if not {"product_id", "name"} <= set(catalog.columns):
            raise ValueError("catalog должен содержать колонки product_id и name")
        if catalog["product_id"].duplicated().any():
            raise ValueError("product_id в каталоге должны быть уникальными")
        if catalog["name"].isna().any():
            raise ValueError("в каталоге есть пустые названия")
        self.catalog = catalog[["product_id", "name"]].reset_index(drop=True)
        self.names = self.catalog["name"].astype(str).tolist()
        self.ids = self.catalog["product_id"].tolist()
        self._pos = {pid: i for i, pid in enumerate(self.ids)}

        norm = [normalize(n) for n in self.names]
        self._tfidf = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4)).fit(norm)
        self._M = self._tfidf.transform(norm)

        self._model = None
        self._E_sym = self._E_doc = None
        methods = {s: self.config[s]["method"] for s in METHODS}
        if any(m in SEMANTIC for m in methods.values()):
            self._E_sym = self._embed(norm, "sym")
            if methods["search"] in SEMANTIC:
                self._E_doc = self._embed(norm, "doc")

    # ------------------------------------------------------------ служебное
    def info(self) -> dict[str, Any]:
        return {
            "module_version": __version__,
            "config_version": self.config.get("version"),
            "data_version": self.config.get("data_version"),
            "model": self.config.get("model", {}).get("name"),
            "methods": {s: self.config[s]["method"] for s in METHODS},
            "catalog_size": len(self.ids),
        }

    def _embed(self, texts: list[str], role: str) -> np.ndarray:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # импорт только если нужна модель
            self._model = SentenceTransformer(self.config["model"]["name"])
        m = self.config["model"]
        prefix = m.get("doc_prefix", "") if role == "doc" else m.get("query_prefix", "")
        return self._model.encode([prefix + t for t in texts], normalize_embeddings=True,
                                  batch_size=64, show_progress_bar=False)

    def _tfidf_sims(self, text: str) -> np.ndarray:
        q = self._tfidf.transform([normalize(text)])
        return (self._M @ q.T).toarray().ravel()

    def _sem_sims(self, text: str, role: str = "sym") -> np.ndarray:
        E = self._E_doc if role == "doc" else self._E_sym
        return E @ self._embed([normalize(text)], role)[0]

    def _combine(self, scenario: str, t, s):
        method = self.config[scenario]["method"]
        if method == "tfidf":
            return t
        if method == "semantic":
            return s
        return (t + s) / 2

    def _row(self, i: int, score: float) -> dict:
        return {"product_id": self.ids[i], "name": self.names[i], "score": round(float(score), 4)}

    @staticmethod
    def _check_items(items) -> list[dict]:
        if not isinstance(items, list) or not items:
            raise ValueError("items должен быть непустым списком словарей {'id', 'name'}")
        for it in items:
            if not isinstance(it, dict) or "id" not in it:
                raise ValueError("каждый элемент items должен быть словарём с ключами 'id' и 'name'")
            if not isinstance(it.get("name"), str) or not normalize(it["name"]):
                raise ValueError(f"пустое или не строковое название у элемента {it.get('id')!r}")
        return items

    # ----------------------------------------------- сценарий 1: идентичные
    def pair_scores(self, texts_a: list[str], texts_b: list[str]) -> np.ndarray:
        """Оценка «это один и тот же товар» для пар текстов (0..1, выше значит вероятнее)."""
        cfg = self.config["identical"]
        na, nb = [normalize(x) for x in texts_a], [normalize(x) for x in texts_b]
        A, B = self._tfidf.transform(na), self._tfidf.transform(nb)
        t = np.asarray(A.multiply(B).sum(axis=1)).ravel()
        s = None
        if cfg["method"] != "tfidf":
            s = (self._embed(na, "sym") * self._embed(nb, "sym")).sum(axis=1)
        score = self._combine("identical", t, s)
        if cfg.get("use_attribute_check", True):
            score = score * np.array([attrs_compatible(x, y) for x, y in zip(texts_a, texts_b)], dtype=float)
        return score

    def match(self, items: list[dict], top_k: int = 3) -> list[dict]:
        """Предварительное сопоставление: для каждого товара из items кандидаты из каталога и решение."""
        cfg = self.config["identical"]
        thr, margin = cfg["threshold"], cfg.get("review_margin", 0.1)
        results = []
        for item in self._check_items(items):
            t = self._tfidf_sims(item["name"])
            s = self._sem_sims(item["name"]) if cfg["method"] != "tfidf" else None
            sims = self._combine("identical", t, s)
            scored = []
            for i in np.argsort(-sims, kind="stable")[: max(50, top_k)]:
                score = float(sims[i])
                if cfg.get("use_attribute_check", True) and not attrs_compatible(item["name"], self.names[i]):
                    score = 0.0
                scored.append((int(i), score))
            scored.sort(key=lambda x: -x[1])
            top = scored[:top_k]
            best = top[0][1] if top else 0.0
            decision = "match" if best >= thr else "review" if best >= thr - margin else "no_match"
            results.append({"id": item["id"], "name": item["name"], "decision": decision,
                            "candidates": [self._row(i, sc) for i, sc in top]})
        return results

    # ------------------------------------------------ сценарий 2: аналоги
    def analogs(self, product_id, top_k: int = 5, candidate_ids: Iterable | None = None) -> list[dict]:
        if product_id not in self._pos:
            raise ValueError(f"неизвестный product_id: {product_id!r}")
        i = self._pos[product_id]
        t = (self._M @ self._M[i].T).toarray().ravel()
        s = self._E_sym @ self._E_sym[i] if self.config["analogs"]["method"] != "tfidf" else None
        sims = self._combine("analogs", t, s).astype(float).copy()
        sims[i] = -np.inf                                   # сам товар не предлагаем
        if candidate_ids is not None:
            mask = np.full(len(self.ids), -np.inf)
            mask[[self._pos[c] for c in candidate_ids if c in self._pos]] = 0.0
            sims = sims + mask
        order = [j for j in np.argsort(-sims, kind="stable")[:top_k] if np.isfinite(sims[j])]
        return [self._row(int(j), sims[j]) for j in order]

    # --------------------------------------------- сценарий 3: поиск по тексту
    def search(self, query: str, top_k: int = 10) -> list[dict]:
        if not isinstance(query, str) or not normalize(query):
            raise ValueError("query должен быть непустой строкой")
        cfg = self.config["search"]
        method = cfg["method"]
        if method == "tfidf":
            sims = self._tfidf_sims(query)
        elif method == "semantic":
            sims = self._sem_sims(query, "doc")
        else:                                               # rrf: складываем места двух методов
            k_rrf, depth = cfg.get("rrf_k", 60), cfg.get("depth", 100)
            fused: dict[int, float] = {}
            for sims_part in (self._tfidf_sims(query), self._sem_sims(query, "doc")):
                for rank, j in enumerate(np.argsort(-sims_part, kind="stable")[:depth]):
                    fused[int(j)] = fused.get(int(j), 0.0) + 1 / (k_rrf + rank + 1)
            top = sorted(fused.items(), key=lambda x: (-x[1], x[0]))[:top_k]
            return [self._row(j, sc) for j, sc in top]
        order = np.argsort(-sims, kind="stable")[:top_k]
        return [self._row(int(j), sims[j]) for j in order]
