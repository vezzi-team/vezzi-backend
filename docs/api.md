# API для iOS-приложения

Полная спецификация: `GET /openapi.json` на сервере или файл [`openapi.json`](openapi.json) в репозитории.
По ней можно сгенерировать Swift-клиент ([swift-openapi-generator](https://github.com/apple/swift-openapi-generator)):
у каждой операции понятный `operationId` (`register`, `calculate_plans` и так далее).
Интерактивная документация: `/docs` (Swagger UI) и `/redoc`.

## Общие правила

- Базовый адрес: `https://<домен>/api/v1`. Только HTTPS, App Transport Security ослаблять не нужно.
- Формат: JSON, UTF-8. Время в ответах всегда UTC без долей секунды: `2026-11-02T09:30:00Z`.
  Подходит стандартный `JSONDecoder.dateDecodingStrategy = .iso8601`, свой форматтер не нужен.
- Имена полей в `snake_case`: удобно включить `keyDecodingStrategy = .convertFromSnakeCase`.
- **Деньги в целых копейках**: `8999` = 89,99 ₽. **Время в секундах, расстояния в метрах.**
- Координаты всегда объектом `{"latitude": 60.0086, "longitude": 30.2587}`, порядок не перепутать.
- Каждый ответ содержит заголовок `X-Request-ID`. Клиент может прислать свой (8–64 символа `A-Z a-z 0-9 . _ -`).
  Если что-то сломалось, этот идентификатор нужен, чтобы найти запрос в логах сервера.

## Авторизация

```text
POST /auth/register  {email, password}      -> 201 {user, tokens}
POST /auth/login     {email, password}      -> 200 {user, tokens}
POST /auth/refresh   {refresh_token}        -> 200 tokens
POST /auth/logout    {refresh_token}        -> 204
GET  /users/me                              -> 200 user
POST /users/me/password {current_password, new_password} -> 200 tokens
DELETE /users/me                            -> 204
```

`tokens` = `{access_token, refresh_token, token_type: "bearer", expires_in}`.

- **access_token** живёт 30 минут. Передавайте в заголовке `Authorization: Bearer <access_token>`.
- **refresh_token** живёт 30 дней и **одноразовый**: `/auth/refresh` возвращает новую пару, старый
  refresh-токен сразу перестаёт работать.
- Оба токена храните в **Keychain**, не в UserDefaults (требование N03).
- Пароль: от 8 до 128 символов.

Рекомендуемая логика клиента:

1. На любой ответ `401` с кодом `invalid_token` вызвать `/auth/refresh` и повторить запрос один раз.
2. **Не отправлять два refresh одновременно.** Если два запроса получили 401, второй должен дождаться
   результата первого обновления. Повторное использование старого refresh-токена сервер считает
   кражей и завершает сессию устройства (`refresh_token_reused`).
3. Если `/auth/refresh` вернул 401, удалить токены и показать экран входа.
4. Кнопка «Выйти»: `/auth/logout` с refresh-токеном, затем удалить токены из Keychain.
5. **Удаление аккаунта** (обязательно по правилу App Store 5.1.1(v)): подтверждение у пользователя,
   затем `DELETE /users/me`. Удаляются аккаунт, корзины и планы.

Каждый вход создаёт отдельную сессию: выход на телефоне не разлогинивает планшет. Смена пароля
завершает все остальные сессии и возвращает новые токены для текущего устройства.

Вход через Google и Apple планируется позже, база данных к этому готова (`docs/decisions.md`).

## Ошибки

Любая ошибка приходит в одном формате:

```json
{"code": "items_limit_exceeded", "message": "В корзине может быть не больше 30 разных товаров", "request_id": "0e31cf48f4a3...", "details": null}
```

`message` можно показывать пользователю. Логику стройте по `code`, текст может меняться.
Для `validation_error` в `details` список полей: `[{"field": "body.password", "message": "..."}]`.

| HTTP | code | Когда |
|---|---|---|
| 400 | `wrong_password` | Неверный текущий пароль при смене пароля |
| 401 | `not_authenticated` | Нет заголовка Authorization |
| 401 | `invalid_token` | Access-токен истёк или неверный: нужно обновить |
| 401 | `invalid_credentials` | Неверный email или пароль |
| 401 | `invalid_refresh_token`, `refresh_token_expired`, `refresh_token_reused` | Нужно войти заново |
| 403 | `permission_denied` | Действие только для администратора |
| 404 | `cart_not_found`, `plan_not_found`, `plan_item_not_found`, `product_not_found`, `item_not_found`, `not_found` | Нет такого объекта (или он чужой) |
| 409 | `email_taken` | Email уже зарегистрирован |
| 409 | `plan_already_started` | План уже выбран, второй раз начать нельзя |
| 409 | `plan_expired` | Цены в плане старше 24 часов: рассчитайте заново |
| 409 | `active_plan_exists` | По этой корзине уже идут покупки: завершите или удалите начатый план |
| 409 | `plan_not_active` | Отмечать позиции и завершать можно только начатый план |
| 422 | `validation_error` | Неверный формат запроса |
| 422 | `quantity_limit_exceeded` | Количество товара больше 99 |
| 422 | `items_limit_exceeded` | Больше 30 разных товаров в корзине |
| 422 | `too_many_carts` | Больше 50 корзин у пользователя |
| 422 | `cart_empty` | Попытка посчитать планы для пустой корзины |
| 422 | `invalid_substitution` | Замена для товара, которого нет в корзине |
| 429 | `rate_limited` | Слишком много попыток входа; `details.retry_after_seconds` |
| 503 | `catalog_not_loaded` | Каталог ещё не загружен |
| 503 | `routing_unavailable` | Сервис маршрутов не ответил: показать «Повторить» (F11) |
| 500 | `internal_error` | Ошибка сервера; сообщите `request_id` backend-разработчику |

## Основной сценарий

```text
GET  /catalog                                 что загружено; is_synthetic = демо-данные
GET  /catalog/export                          весь каталог для локального кэша (раздел ниже)
GET  /products/search?q=молоко                до 10 товаров
GET  /products/{id}                           карточка и цены по магазинам (is_fresh)
GET  /stores?latitude=..&longitude=..         магазины, ближайшие первыми
POST /carts {name}                            создать корзину (status = active)
GET  /carts?status=active                     корзины пользователя, можно фильтровать по статусу
PATCH /carts/{id} {name?, status?}            переименовать или сменить статус
POST /carts/{id}/items {product_id, quantity}            добавить (повтор суммирует)
PATCH /carts/{id}/items/{product_id} {quantity}          изменить количество
DELETE /carts/{id}/items/{product_id}                    убрать
GET  /carts/{id}/chain-totals?chain=..       сколько стоит вся корзина в каждой сети
POST /carts/{id}/plans {...}                  посчитать и сохранить до трёх планов
POST /plans/{plan_id}/start                   пользователь выбрал план и пошёл в магазин
PATCH /plans/{plan_id}/items/{item_id} {status}          bought / missing / planned
POST /plans/{plan_id}/complete                покупки закончены
GET  /plans?status=completed                  история
```

Если `GET /catalog` вернул `is_synthetic: true`, покажите пользователю, что цены демонстрационные.

Статусы корзины: `active` (собираю сейчас), `saved` (отложена на потом), `completed` (всё куплено).
Клиент меняет их сам через `PATCH`. Сервер ставит `completed`, когда завершён план этой корзины.

Весовых товаров (мясо и овощи на развес) в каталоге MVP нет: цена у всех товаров за целую упаковку.

### Выгрузка каталога для локального кэша

`GET /catalog/export` отдаёт весь активный каталог: `products`, `stores`, `offers`. Это источник для
`CatalogSource.loadCatalog()` в клиенте. На данных команды это 2,2 МБ без сжатия и около 150 КБ со сжатием,
которое включает Caddy. Проверено настоящим `JSONDecoder` со стратегиями `.convertFromSnakeCase` и `.iso8601`.

Чтобы не качать каталог каждый раз, сохраните заголовок `ETag` и пришлите его в `If-None-Match`.
Если каталог не менялся, придёт пустой ответ `304`. `URLSession` умеет это сам, если не отключать `URLCache`.

| Поле клиента | Поле API | Как перевести |
|---|---|---|
| `CatalogProduct.id`, `CatalogStore.id` | `id` | `String(id)` |
| `CatalogProduct.packageQuantity` | `package_amount` | как есть |
| `CatalogProduct.packageUnit` | `package_unit` | `g`, `ml`, `pcs`, `m`; для показа перевести в г, мл, шт, м |
| `CatalogStore.chainName` | `chain` | как есть |
| `CatalogStore.isActive` | нет | `true`: в выгрузке только работающие магазины |
| `CatalogOffer.id` | `offers[].id` | уже строка `магазин-товар`, не меняется между загрузками |
| `CatalogOffer.productID`, `storeID` | `product_id`, `store_id` | `String(id)` |
| `CatalogOffer.price` | `price_kopecks` | `Decimal(kopecks) / 100`, не через `Double` |
| `CatalogOffer.sourceUpdatedAt` | `source_updated_at` | дата |
| `CatalogOffer.dataOrigin` | `is_synthetic` на верхнем уровне | |

- В выгрузке есть и устаревшие цены, и товары без наличия. Свежесть считает сам клиент:
  `source_updated_at` не старше `offer_max_age_hours`, потому что кэш на телефоне стареет.
- Клиент сейчас хранит записи, которых нет в новой выгрузке. Если цену убрали из каталога, она останется
  в кэше, поэтому её нужно отсеивать по `source_updated_at` или удалять записи, которых нет в ответе.
- Расчёт сумм и планов всё равно делает сервер: локальный кэш нужен для поиска и карточек.

### Сравнение по сетям

`GET /carts/{id}/chain-totals` показывает, сколько стоит вся корзина в каждой сети. Параметр `chain`
можно повторять, чтобы оставить только нужные сети: `?chain=Пятёрочка&chain=Магнит&chain=Перекрёсток`.
Неизвестная сеть даст `422 unknown_chain`.

```json
{
  "chains": [
    {
      "chain": "Перекрёсток",
      "is_complete": true,
      "total_kopecks": 45390,
      "found_total_kopecks": 45390,
      "items_count": 3, "found_items_count": 3, "coverage_percent": 100,
      "missing_products": [],
      "oldest_price_updated_at": "2026-11-02T08:00:00Z",
      "lines": [
        {"product": {"id": 1, "name": "...", "...": "..."}, "quantity": 2, "status": "available",
         "unit_price_kopecks": 9450, "total_kopecks": 18900, "card_price_kopecks": 8900,
         "price_type": "promo", "price_conditions": "до 10.11", "store": {"id": 6, "name": "...", "...": "..."},
         "price_updated_at": "2026-11-02T08:00:00Z", "is_fresh": true}
      ]
    },
    {"chain": "Бристоль", "is_complete": false, "total_kopecks": null, "found_total_kopecks": 37700,
     "items_count": 3, "found_items_count": 2, "coverage_percent": 66,
     "missing_products": [{"id": 2, "...": "..."}], "oldest_price_updated_at": "2026-11-02T08:00:00Z", "lines": ["..."]}
  ],
  "calculated_at": "2026-11-02T09:30:00Z",
  "offer_max_age_hours": 24,
  "data_is_synthetic": true
}
```

- Цена товара в сети: самая низкая свежая цена в наличии среди её магазинов (`store` у строки).
- `total_kopecks` у строки = цена × количество, у сети = сумма строк.
- `coverage_percent`: доля найденных позиций, округлена вниз, поэтому 100 бывает только у полной корзины.
- Если товар не подтверждён, `is_complete: false` и `total_kopecks: null`. Рядом можно показать
  `found_total_kopecks` с подписью вроде «за 2 из 3 товаров», но не как итог: неполная корзина всегда дешевле.
- `status` строки: `available` входит в суммы. Остальные объясняют пропуск: `stale` (цена устарела),
  `out_of_stock` (нет в наличии), `stock_unknown` (наличие неизвестно), `not_sold` (сеть не продаёт товар).
- У пропуска `unit_price_kopecks` и `price_updated_at` показывают последнюю известную цену, если она есть.
- `card_price_kopecks`: цена по карте. Показывайте рядом с обычной, в суммы она не входит (F06).
- `oldest_price_updated_at`: самая старая цена в суммах, это актуальность итога.
- Сети уже отсортированы: полные корзины от дешёвой к дорогой, затем неполные.
- Округления нет, всё в целых копейках (`docs/planning.md`, раздел «Округление»).

### Расчёт планов

```json
POST /api/v1/carts/185ef207-.../plans
{
  "start": {"latitude": 60.0086, "longitude": 30.2587},
  "max_stores": 3,
  "max_total_minutes": 60,
  "substitutions": [{"product_id": 12, "replacement_product_id": 15}],
  "store_ids": null,
  "radius_meters": 420
}
```

- `start` обязателен. Если пользователь запретил геолокацию, он выбирает точку на карте (F05).
- `substitutions`: только замены, которые пользователь **явно подтвердил** (F10).
- `store_ids`: необязательно: ограничить расчёт выбранными магазинами.
- `radius_meters`: необязательно, 100–5000. Радиус круга «сколько готов пройти» вокруг `start`:
  магазины дальше этого расстояния **по прямой** не рассматриваются. Если не передать, ограничения нет.

### Круг «В каком радиусе вы готовы пройтись?»

Экран, где пользователь меняет оранжевый круг вокруг себя, работает так:

1. `GET /stores?latitude=..&longitude=..` один раз: у каждого магазина есть `distance_meters` по прямой.
   Магазины с `distance_meters <= радиус` рисуйте внутри круга (оранжевые звёзды), остальные снаружи.
   Пока пользователь двигает круг, к серверу ходить не нужно.
2. Подпись `~7 мин ходьбы` считайте в приложении: **минуты ≈ радиус в метрах / 60**.
   Пешком путь длиннее прямой: на Комендантском проспекте OSRM даёт коэффициент около 1,4 при скорости
   5 км/ч (83 м/мин), поэтому минута ходьбы соответствует примерно 60 м радиуса. Подпись примерная, поэтому в ней стоит знак `~`.
3. В расчёт передайте `radius_meters`: тот же радиус, что нарисован. В план попадут только магазины из круга.
4. Если внутри круга какие-то товары не продаются, придёт `problem.reason = radius_too_small` и
   `min_required_radius_meters`. Можно предложить: «Увеличьте радиус до N мин» (N = радиус / 60).

Ответ (сокращён):

```json
{
  "status": "ok",
  "plans": [
    {
      "id": "7dd8ff39-...",
      "cart_id": "185ef207-...",
      "status": "planned",
      "rank": 1,
      "total_kopecks": 183492,
      "savings_kopecks": 6400,
      "stores_count": 3,
      "walking_seconds": 1774, "walking_meters": 2464,
      "shopping_seconds": 1800, "total_seconds": 3574,
      "stops": [
        {
          "position": 1,
          "store": {"id": 1, "chain": "Демо-маркет", "name": "Демо-маркет у Горьковской", "latitude": 59.9566, "longitude": 30.3165, "...": "..."},
          "items": [{"id": 41, "product": {"id": 97, "name": "Демо Кофе молотый, 1000 г", "...": "..."}, "quantity": 1, "unit_price_kopecks": 125099, "total_kopecks": 125099, "price_updated_at": "2026-10-30T17:12:00Z", "status": "planned", "alternative_store_id": 3, "alternative_price_kopecks": 129900}],
          "subtotal_kopecks": 125099,
          "shopping_seconds": 600,
          "walk_from_previous_seconds": 415, "walk_from_previous_meters": 576
        }
      ],
      "route": {"provider": "osrm", "uses_road_network": true, "points": [{"latitude": 60.0086, "longitude": 30.2587}, "..."]},
      "data_is_synthetic": true,
      "created_at": "2026-10-30T19:58:31Z", "started_at": null, "completed_at": null
    }
  ],
  "baseline": {"store": {"name": "Демо-гипер на Чкаловском", "...": "..."}, "total_kopecks": 189892},
  "problem": null,
  "calculated_at": "2026-10-30T19:58:31Z",
  "offer_max_age_hours": 24,
  "data_is_synthetic": true
}
```

- Планов до трёх, лучший первым: дешевле, при равной цене быстрее, затем меньше магазинов.
- Чтобы пользователю было проще выбрать, можно подписать первый план «Самый дешёвый», а план с наименьшим
  `total_seconds` «Самый быстрый из вариантов». Это самый быстрый среди присланных планов, а не всех возможных.
- `savings_kopecks`: экономия относительно `baseline` (самый дешёвый план в одном магазине).
  `null`, если сравнивать не с чем или план дороже базы. Не показывайте «экономию 0 ₽» как выгоду.
- `stops` уже в порядке обхода. `walk_from_previous_*`: путь от старта (для первого) или от предыдущего магазина.
- `route.points`: линия от старта до последнего магазина, возврата домой нет.
- Если `route.uses_road_network = false`, сервер работает в тестовом режиме и линия проведена по прямой.
  Такую линию нельзя выдавать пользователю за пешеходный маршрут.
- Каждый план уже сохранён на сервере со статусом `planned` и своим `id`. Новый расчёт по той же
  корзине заменяет невыбранные планы прошлого расчёта.

Если план составить нельзя, приходит `"status": "no_plans"`, `"plans": []` и объяснение (F11):

| `problem.reason` | Что показать |
|---|---|
| `items_unavailable` | Товары из `unavailable_products` сейчас нигде не продаются по свежей цене |
| `store_limit_too_low` | Нужно больше магазинов: `min_required_stores` |
| `time_limit_too_low` | Не хватает времени: минимум `min_required_minutes` |
| `route_unavailable` | Не удалось построить пеший маршрут до магазинов |
| `radius_too_small` | В круге продаются не все товары (`unavailable_products`); хватит радиуса `min_required_radius_meters` |

### Выбор плана и покупки

| Статус | Что значит | Как перейти дальше |
|---|---|---|
| `planned` | План рассчитан | `POST /plans/{id}/start` |
| `active` | Идут покупки | `POST /plans/{id}/complete` |
| `completed` | Покупки закончены | |

1. Пользователь выбрал план: `POST /plans/{id}/start`. Остальные варианты этого расчёта удаляются.
   Если цены в плане старше 24 часов, придёт `409 plan_expired`: нужно пересчитать.
2. В магазине пользователь отмечает позиции: `PATCH /plans/{id}/items/{item_id}` с
   `{"status": "bought"}` или `{"status": "missing"}` (нет на полке). Ответ: план целиком.
3. Для `missing` подскажите запасной вариант: `alternative_store_id` и `alternative_price_kopecks`.
   Это другой магазин **этого же маршрута**, где товар тоже есть, поэтому лишний путь не нужен.
   Если `null`, товар продаётся только в этом магазине.
4. «Готово»: `POST /plans/{id}/complete`. План и корзина получают статус `completed`.
5. История: `GET /plans?status=completed` отдаёт краткие строки (`items_count`, `bought_count`,
   `total_kopecks`, `savings_kopecks`), полный план с маршрутом: `GET /plans/{id}`.

План хранит цены на момент расчёта, поэтому через месяц он покажет те же суммы. По одной корзине
одновременно может идти только один план (`409 active_plan_exists`). Удаление корзины план не удаляет,
у него просто становится `cart_id: null`.

## Карта в приложении

Backend отдаёт готовую линию маршрута. На карте её достаточно нарисовать полилинией по `route.points`
и поставить метки магазинов из `stops`. Чтобы линия выглядела аккуратно, включите скругление углов
и белую подложку под ней (`docs/routing.md`, раздел про красоту линии).
Источник маршрута OpenStreetMap, поэтому рядом с картой нужна подпись «© участники OpenStreetMap».
