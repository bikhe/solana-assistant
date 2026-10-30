# CLAUDE.md

Правила для агентов, которые работают в этом репозитории. Сначала прочитай [docs/PLAN.md](docs/PLAN.md) и [CONTRIBUTING.md](CONTRIBUTING.md).

## Проект

Solana: голосовой ассистент для ПК (Windows, Linux, macOS), русский в первую очередь, английский тоже. Два процесса:

- `core/`: Python 3.12, asyncio, uv. Вся логика: аудио, wake word, STT, TTS, LLM, инструменты, MCP, скиллы, настройки.
- `app/`: Tauri 2 + React + TypeScript + Tailwind CSS. Трей, оверлей, чат, настройки. Запускает core и говорит с ним по WebSocket (JSON-RPC 2.0).
- `protocol/ipc.schema.json`: контракт между ними. TS-типы и pydantic-модели генерируются из него.

## Главные правила

1. Один пакет (WP) = одна ветка `wp-<N>-<slug>` = один PR в `main`. Меняй только папки своего пакета.
2. Не меняй `protocol/`, `core/solana_core/*/base.py`, `core/solana_core/tools/base.py` и `core/solana_core/config/models.py` в своём PR. Если без этого нельзя, опиши изменение в PR и используй временный адаптер у себя.
3. Всё внешнее (микрофон, сеть, модели, ОС) прячь за интерфейсом из `base.py`. У каждого интерфейса есть Fake-реализация: тесты работают без железа, сети и моделей.
4. Только open source зависимости (MIT, Apache-2.0, BSD, MPL и подобные). Облачные API только как опция: каждая функция должна работать локально. Проприетарные движки (например, Porcupine) не используем.
5. Эталонная машина пользователя: AMD RX 6600 8 ГБ, без CUDA. Для локальных моделей на GPU выбирай Vulkan (llama.cpp, whisper.cpp), CPU как запасной вариант.
6. Пользовательский текст (ответы, ошибки, подписи UI) по-русски, с английским переводом там, где уже есть i18n. Код, комментарии, имена и коммиты по-английски.
7. Перед PR прогони проверки ниже. CI должен быть зелёным на трёх ОС.

## Команды

Core (из `core/`):

```sh
uv sync                                   # зависимости
uv run solana-core --fake --port 8765 --token dev   # демо-сценарий событий
uv run ruff check . && uv run ruff format --check .
uv run mypy                               # strict
uv run pytest -q
uv run python scripts/gen_protocol.py     # после правки protocol/ipc.schema.json
```

App (из `app/`):

```sh
pnpm install
pnpm tauri dev           # окно + core из исходников в fake-режиме (SOLANA_FAKE=0 для настоящего)
pnpm dev                 # только веб-часть: открой http://localhost:1420/?port=8765&token=dev
pnpm lint && pnpm format:check && pnpm typecheck && pnpm test
pnpm gen:protocol        # после правки protocol/ipc.schema.json
```

Rust (из `app/src-tauri/`): `cargo fmt --check && cargo clippy --all-targets -- -D warnings`.

## Где что лежит

| Что | Где |
| --- | --- |
| JSON-RPC диспетчер, WebSocket, обработчики | `core/solana_core/server/` |
| Состояние ассистента, подтверждения, шина событий | `core/solana_core/server/core.py` |
| Fake-сценарий и тестовые данные | `core/solana_core/fake/` |
| Контракты провайдеров | `core/solana_core/{audio,wake,stt,tts,brain,pc}/base.py` |
| `Tool`, `ToolRegistry` | `core/solana_core/tools/` |
| Настройки (TOML) и секреты (keyring) | `core/solana_core/config/` |
| Клиент JSON-RPC для UI | `app/src/lib/rpc.ts` |
| Запуск core из Tauri | `app/src-tauri/src/core.rs` |

## Как устроено

- core печатает в stdout строку `SOLANA_CORE_READY {"port": .., "token": ".."}`, когда готов. Tauri читает её и отдаёт фронтенду командой `core_info`.
- Методы, чьи пакеты ещё не готовы, отвечают ошибкой `-32001`. В `--fake` они работают на тестовых данных, чтобы UI можно было делать заранее.
- Обработчик метода получает провалидированную pydantic-модель параметров и возвращает модель результата. Новый метод: добавь в схему, перегенерируй, зарегистрируй через `@rpc.method("...")` в `server/handlers.py`. Тест `test_every_protocol_method_has_a_handler` проверяет, что ничего не забыто.
- События шлются через `core.bus.emit("<event>", <Model>(...))`; имя и тип модели проверяются по схеме.
