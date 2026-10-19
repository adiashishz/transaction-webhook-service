COMPOSE = docker compose

.PHONY: dev down up logs run worker test migrate makemigrations smoke

## Start only Postgres and Redis (run Django and Celery locally with uv)
dev:
	$(COMPOSE) up -d db redis

## Stop all containers
down:
	$(COMPOSE) down

## Build and run the full stack (db, redis, web on :8000, worker)
up:
	$(COMPOSE) up -d --build

## Tail container logs, e.g. make logs s=worker
logs:
	$(COMPOSE) logs -f $(s)

## Run the API locally on :8000
run:
	uv run python manage.py runserver 8000

## Run the Celery worker (with the recovery sweep scheduler) locally
worker:
	uv run celery -A config worker --beat --pool=threads --concurrency=32 --loglevel=info

## Run the test suite (needs make dev first)
test:
	uv run pytest

## Apply migrations
migrate:
	uv run python manage.py migrate

## Create migrations after model changes
makemigrations:
	uv run python manage.py makemigrations

## Run the end-to-end smoke test, e.g. make smoke url=http://localhost:8000
smoke:
	uv run python scripts/smoke_test.py --base-url $(or $(url),http://localhost:8000)
