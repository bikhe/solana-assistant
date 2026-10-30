# Как участвовать

Проект открыт (MIT) и строится пакетами работ (WP) из [docs/PLAN.md](docs/PLAN.md). Правила одинаковые для людей и агентов.

## Подготовка

Нужны: [uv](https://docs.astral.sh/uv/), Node.js 22 и pnpm 10, Rust stable, системные зависимости Tauri ([список для каждой ОС](https://v2.tauri.app/start/prerequisites/)).

```sh
cd core && uv sync
cd ../app && pnpm install
pnpm tauri dev
```

Должно открыться окно Solana со статусом «core: подключён» и меняющимся состоянием (это fake-режим core).

## Ветки и PR

1. Ветка `wp-<номер>-<slug>` от свежего `main`, например `wp-1-wake-word`.
2. Меняй только папки своего пакета (они перечислены в плане).
3. Контракты (`protocol/`, `base.py`, модель настроек) меняются отдельным маленьким PR, который согласует владелец проекта.
4. В описании PR отметь каждый пункт «Готово, когда» из плана и приложи замеры, если пакет их требует.
5. PR принимается, когда CI зелёный на Windows, Linux и macOS.

## Код

- Python: ruff (lint и format), mypy strict, pytest. Асинхронный код на asyncio, блокирующие вызовы через `asyncio.to_thread`.
- TypeScript: ESLint, Prettier, Vitest, строгий `tsconfig`.
- Rust: `cargo fmt`, `cargo clippy -D warnings`.
- Тесты не должны требовать микрофона, сети, GPU или скачанных моделей. Используй Fake-реализации из `base.py` и фикстуры в `core/tests/`.
- Сообщения коммитов по-английски, в повелительном наклонении: `Add Silero VAD detector`.

## Зависимости

Только с открытой лицензией. Облачные сервисы допустимы как опция рядом с локальной реализацией. Веса моделей в git не коммитим.

## Протокол

См. [protocol/README.md](protocol/README.md). После правки схемы запусти оба генератора:

```sh
cd core && uv run python scripts/gen_protocol.py
cd ../app && pnpm gen:protocol
```
