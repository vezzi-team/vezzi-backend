"""Сквозная проверка работающего сервера: весь путь пользователя через настоящий HTTPS.

Создаёт временного пользователя, собирает корзину, сравнивает сети, считает план,
проходит его и удаляет аккаунт. Запускается и локально, и после развёртывания:

    uv run python deploy/smoke_test.py https://vezzi.vps.webdock.cloud
    uv run python deploy/smoke_test.py https://localhost --insecure
"""

import argparse
import sys
import time
import uuid
from typing import Any

import httpx2

# Метро «Комендантский проспект»: магазины каталога команды стоят рядом.
START = {"latitude": 60.0086, "longitude": 30.2587}
QUERIES = ("Valio молоко ультрапастеризованное 2,5", "тушёнка свиная", "горчица дижонская")


class Check:
    def __init__(self) -> None:
        self.failed = 0

    def __call__(self, title: str, passed: bool, detail: object = "") -> None:
        print(f"{'OK  ' if passed else 'FAIL'} {title} {detail}")
        self.failed += not passed


def run(base_url: str, insecure: bool) -> int:
    client = httpx2.Client(base_url=base_url, verify=not insecure, timeout=30)
    check = Check()

    check("сервис жив", client.get("/health").status_code == 200)
    check("база отвечает", client.get("/ready").status_code == 200)
    build = client.get("/version").json()
    check("версия сборки", "version" in build, build)
    check("без токена нельзя", client.get("/api/v1/carts").status_code == 401)

    email = f"smoke-{uuid.uuid4().hex[:12]}@example.com"
    password = uuid.uuid4().hex
    auth = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    check("регистрация", auth.status_code == 201)
    client.headers["Authorization"] = f"Bearer {auth.json()['tokens']['access_token']}"

    try:
        catalog = client.get("/api/v1/catalog").json()
        check(
            "каталог загружен", catalog["is_loaded"], f"свежих цен: {catalog['fresh_offers_count']}"
        )
        check("данные помечены как демо", catalog["is_synthetic"])

        export = client.get("/api/v1/catalog/export")
        check(
            "выгрузка каталога", export.status_code == 200, f"цен: {len(export.json()['offers'])}"
        )
        cached = client.get(
            "/api/v1/catalog/export", headers={"If-None-Match": export.headers["ETag"]}
        )
        check("повторная выгрузка не качается заново", cached.status_code == 304)

        cart = client.post("/api/v1/carts", json={"name": "Проверка"}).json()
        for query in QUERIES:
            found = client.get("/api/v1/products/search", params={"q": query}).json()
            check(f"поиск «{query}»", bool(found), found[0]["name"] if found else "")
            client.post(
                f"/api/v1/carts/{cart['id']}/items",
                json={"product_id": found[0]["id"], "quantity": 2},
            )

        chains = client.get(f"/api/v1/carts/{cart['id']}/chain-totals").json()["chains"]
        complete = [chain for chain in chains if chain["is_complete"]]
        check("сравнение сетей", bool(complete), f"полных корзин: {len(complete)} из {len(chains)}")

        started = time.perf_counter()
        response = client.post(
            f"/api/v1/carts/{cart['id']}/plans",
            json={"start": START, "max_stores": 3, "max_total_minutes": 120},
        )
        milliseconds = (time.perf_counter() - started) * 1000
        body: dict[str, Any] = response.json()
        check("расчёт планов", body.get("status") == "ok", f"{milliseconds:.0f} мс")
        plan = body["plans"][0]
        check("маршрут по улицам", plan["route"]["uses_road_network"], plan["route"]["provider"])

        plan_url = f"/api/v1/plans/{plan['id']}"
        check("план начат", client.post(f"{plan_url}/start").json()["status"] == "active")
        item_id = plan["stops"][0]["items"][0]["id"]
        marked = client.patch(f"{plan_url}/items/{item_id}", json={"status": "bought"})
        check("отметка «куплено»", marked.status_code == 200)
        check("план завершён", client.post(f"{plan_url}/complete").json()["status"] == "completed")
        history = client.get("/api/v1/plans", params={"status": "completed"}).json()
        check("история", len(history) == 1)
    finally:
        deleted = client.delete("/api/v1/users/me").status_code
        check("аккаунт удалён", deleted == 204)

    print("Проверка пройдена" if not check.failed else f"Ошибок: {check.failed}")
    return 1 if check.failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Сквозная проверка сервера")
    parser.add_argument("base_url")
    parser.add_argument(
        "--insecure", action="store_true", help="не проверять сертификат (только localhost)"
    )
    arguments = parser.parse_args()
    sys.exit(run(arguments.base_url, arguments.insecure))
