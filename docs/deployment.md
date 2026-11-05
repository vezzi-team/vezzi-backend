# Развёртывание на VPS

Сервер: Webdock (Дания), Ubuntu 24.04, 4 vCPU / 8 ГБ / 50 ГБ, пользователь `deploy`, вход `ssh vezzi`.
Сервер развёрнут по этим шагам 05.11.2026: **https://vezzi.vps.webdock.cloud**. Инструкция нужна для
обновления и повторной установки. Выполнять по одному, проверяя вывод.

Схема на сервере: наружу открыт только Caddy (80/443), он сам получает HTTPS-сертификат Let's Encrypt.
API, PostgreSQL и OSRM работают внутри Docker-сети и снаружи недоступны.

## 0. Сначала локальная репетиция

Перед сервером всё проверяется на своём компьютере в той же конфигурации. Рабочую базу разработки это не трогает:

```bash
./deploy/osrm/prepare.sh                     # один раз: граф карты
./deploy/rehearsal.sh <каталог.xlsx>         # сборка, каталог и сквозная проверка
./deploy/rehearsal.sh --clean                # удалить всё после проверки
```

## 1. Подготовка сервера (один раз)

```bash
ssh vezzi                     # дальше команды выполняются на сервере: deploy@vezzi:~$
uname -r && df -h && free -h  # проверить ядро, диск и память
```

Docker ставится по [официальной инструкции для Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
(раздел «Install using the apt repository»), затем:

```bash
sudo usermod -aG docker deploy   # чтобы docker работал без sudo; потом перезайти по ssh
docker run --rm hello-world
```

Firewall. **Сначала разрешить SSH**, иначе потеряется доступ (на крайний случай есть WebSSH в панели Webdock):

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443
sudo ufw enable
sudo ufw status verbose
```

## 2. Адрес сервера

Покупать домен не нужно. У сервера есть бесплатное имя от Webdock: `vezzi.vps.webdock.cloud`, оно уже
указывает на `193.181.220.173` (проверено 05.11.2026). На него Caddy сам получит сертификат Let's Encrypt.

Просто IP не подходит: iOS по умолчанию ходит только по HTTPS, а токены и пароли нельзя отправлять открытым
текстом. Для IP нужен отдельный короткий сертификат на 6 дней, и работу этого режима в Caddy мы не проверяли.
Если Webdock-имя не получит сертификат, запасной бесплатный вариант: `193-181-220-173.sslip.io`.

## 3. Первый запуск

```bash
git clone https://github.com/vezzi-team/vezzi-backend.git
cd vezzi-backend
cp .env.example .env
nano .env
```

В `.env` обязательно поменять:

```bash
ENVIRONMENT=production
API_DOMAIN=vezzi.vps.webdock.cloud          # адрес из шага 2
POSTGRES_PASSWORD=<длинный случайный>       # python3 -c "import secrets; print(secrets.token_urlsafe(24))"
JWT_SECRET_KEY=<длинный случайный>          # python3 -c "import secrets; print(secrets.token_urlsafe(48))"
ROUTING_PROVIDER=osrm
```

Чтобы не набирать длинную команду, добавьте сокращение в `~/.bashrc` и перезайдите:

```bash
alias dc="docker compose -f compose.yaml -f deploy/compose.prod.yaml --profile routing"
```

```bash
./deploy/osrm/prepare.sh   # карта Петербурга для маршрутов, ~2 минуты
BUILD_COMMIT=$(git rev-parse --short HEAD) dc up -d --build
dc ps
curl https://vezzi.vps.webdock.cloud/health    # {"status":"ok"}
curl https://vezzi.vps.webdock.cloud/ready     # {"status":"ok","database":"ok"}
curl https://vezzi.vps.webdock.cloud/version   # версия и коммит сборки
```

Администратор и данные:

```bash
dc exec api vezzi create-admin --email <ваша почта>
```

Каталог загружается через `/docs` под администратором (`POST /admin/catalog/imports`, поле `is_synthetic`)
или командой `vezzi import-catalog`. Файл, скопированный в контейнер через `dc cp`, потом удаляется от root:
`dc exec -T -u root api rm -f /tmp/catalog.xlsx`. Цены в текущей таблице команды растянуты на 10 дней, поэтому для демо
в `.env` на сервере временно нужен `OFFER_MAX_AGE_HOURS=264`. Для настоящих суточных данных верните 24.

Сквозная проверка с компьютера, она проходит весь путь пользователя и удаляет за собой тестовый аккаунт:

```bash
uv run python deploy/smoke_test.py https://vezzi.vps.webdock.cloud
```

Проверить с iPhone **через мобильный интернет**, а не только с сервера: открыть `https://vezzi.vps.webdock.cloud/docs`.

## 4. Обновление

```bash
# на компьютере разработчика, в папке проекта
git archive HEAD | ssh vezzi 'tar -x -C ~/vezzi-backend'
git rev-parse --short HEAD                   # этот коммит записать в .env на сервере

# на сервере
cd ~/vezzi-backend
nano .env                                    # BUILD_COMMIT=<коммит>
dc up -d --build
curl https://vezzi.vps.webdock.cloud/version
```

Миграции применяются автоматически: сервис `migrate` запускает `alembic upgrade head` перед стартом API.

## 5. Резервные копии (N04)

```bash
./deploy/backup.sh                          # копия в backups/vezzi-<дата>.dump
crontab -e                                  # ежедневно в 03:15:
# 15 3 * * * cd /home/deploy/vezzi-backend && ./deploy/backup.sh >> backups/backup.log 2>&1
```

Копии хранятся 14 дней. Снимки Webdock не заменяют `pg_dump`: копию нужно уметь восстановить.

**Проверка восстановления** (ТЗ требует не дольше 30 минут). Восстанавливаем в отдельную базу,
рабочая не трогается:

```bash
time (
  docker compose exec -T db createdb -U vezzi vezzi_restore_check &&
  docker compose exec -T db pg_restore -U vezzi -d vezzi_restore_check < backups/<файл>.dump
)
docker compose exec -T db psql -U vezzi -d vezzi_restore_check -c "select count(*) from users; select count(*) from carts; select count(*) from plans; select count(*) from offers;"
docker compose exec -T db dropdb -U vezzi vezzi_restore_check
```

Количество записей должно совпасть с рабочей базой на момент копии. Время и результат записать в протокол испытаний.

## 6. Полезные команды

```bash
dc logs -f api                  # логи API (с request_id)
dc exec db psql -U vezzi        # консоль PostgreSQL
dc restart api
```

## Что запрещено

- Открывать наружу порты 5432 (PostgreSQL), 8000 (uvicorn) и 5000 (OSRM).
- Хранить `.env` в git или пересылать секреты в чатах.
- Включать парольный вход по SSH и отключать доступ по ключу.
