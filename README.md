# QuickBite Analytics Platform

Портфолио-проект по продуктовой аналитике доставки еды. Stage 1 описывает [архитектуру](docs/architecture/overview.md), [модель](docs/data_model/data_dictionary.md) и [метрики](docs/data_model/relationships.md). Stage 2 добавляет PostgreSQL, ClickHouse и исполняемые схемы.

## Запуск

Нужны Docker Engine или Docker Desktop с Linux-контейнерами и Docker Compose V2. Запускать команды из корня репозитория.

```bash
docker compose up -d --wait --wait-timeout 180
docker compose ps
```

Ожидаемый статус обоих сервисов — `healthy`. Инициализация на пустых named volumes применяет DDL и загружает seed через `/docker-entrypoint-initdb.d`. PostgreSQL хранит восемь транзакционных таблиц. ClickHouse создаёт восемь пустых landing-таблиц `pg_*` и загружает шесть продуктовых событий в `product_events`. Перенос данных из PostgreSQL и dbt запланированы на следующий этап.

| Сервис | Адрес на машине | Протокол |
| --- | --- | --- |
| PostgreSQL | `127.0.0.1:55432` | PostgreSQL |
| ClickHouse | `127.0.0.1:58123` | HTTP |
| ClickHouse | `127.0.0.1:59000` | Native |

Имя базы и пользователя по умолчанию — `quickbite`. Пароли в Compose — публичные локальные значения для стенда с loopback-портами. Для переопределения скопируйте [.env.example](.env.example) в `.env` и заполните нужные переменные. Git игнорирует `.env`.

## Проверки

```bash
bash tests/smoke.sh
bash tests/smoke.sh --replay
```

В Windows скрипт запускается из Git Bash или WSL с доступом к `docker compose`. Вариант без Bash на хосте работает из PowerShell после запуска контейнеров.

```powershell
docker compose exec -T postgres sh -ec 'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -v ON_ERROR_STOP=1 -f /quickbite-tests/smoke.sql'
docker compose exec -T clickhouse sh -ec 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" --multiquery --queries-file /quickbite-tests/smoke.sql'
```

Smoke проверяет подключение и чтение в обеих базах. PostgreSQL выполняет INSERT с откатом, отклоняет нарушения PK/FK и проверяет итоги seed. ClickHouse проверяет landing-таблицы, шесть уникальных событий, связь с корзиной и INSERT в сессионную таблицу. В PostgreSQL seed использует `ON CONFLICT` по PK, в ClickHouse — фиксированные UUID и проверку наличия ключа перед вставкой. Повтор ClickHouse рассчитан на одного писателя. `--replay` повторно применяет DDL и seed к существующим данным и снова запускает smoke.

[GitHub Actions](.github/workflows/stage-2.yml) проверяет Compose и синтаксис Bash, запускает две базы, выполняет smoke и replay. Затем пересоздаёт контейнеры с теми же volumes и повторяет smoke.

PostgreSQL DDL обеспечивает PK, FK, проверки типов операций, связи возврата с исходным списанием и единственный терминальный статус. Проверка порядка этапов по времени, суммы частичных возвратов, валидности IANA-зон, первого доставленного заказа в A/B и логических FK ClickHouse остаётся в контракте источника и следующих проверках загрузки.

## Типовые ошибки

| Симптом | Действие |
| --- | --- |
| `docker` или `compose` не найден | Проверьте `docker compose version` и запуск Docker Desktop или Engine |
| Порт занят или запрещён | Переопределите `POSTGRES_PORT`, `CLICKHOUSE_HTTP_PORT` или `CLICKHOUSE_NATIVE_PORT` в `.env` |
| Сервис `unhealthy` | Посмотрите `docker compose ps` и `docker compose logs postgres clickhouse` |
| После изменения SQL осталась старая схема | Init применяется при создании пустого хранилища. Для повторного применения текущего DDL и seed на исправном стенде используйте `--replay`. Изменения существующих колонок требуют миграции |
| После изменения пароля PostgreSQL отклоняет вход | Переменные инициализации PostgreSQL не меняют роль в существующем volume. Используйте первоначальные параметры или измените пароль роли в PostgreSQL |
| Нужен свежий стенд с сохранением старых данных | Запустите отдельный Compose-проект с `docker compose -p quickbite-fresh up -d --wait` и свободными портами |

`docker compose down` останавливает стенд и сохраняет volumes.
