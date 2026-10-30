# Solana

Голосовой ассистент для ПК: локальный wake word «Эй, Солана», управление компьютером, MCP и скиллы. Работает на Windows, Linux и macOS, мозг на выбор: облачная LLM, локальная модель или гибрид.

Проект в самом начале. План разработки, архитектура и пакеты задач для агентов: [docs/PLAN.md](docs/PLAN.md).

## Быстрый старт для разработки

Нужны uv, Node.js 22 + pnpm, Rust и [зависимости Tauri](https://v2.tauri.app/start/prerequisites/).

```sh
cd core && uv sync
cd ../app && pnpm install && pnpm tauri dev
```

Откроется окно со статусом «core: подключён» и демо-сценарием событий (fake-режим). Правила для участников и агентов: [CONTRIBUTING.md](CONTRIBUTING.md), [CLAUDE.md](CLAUDE.md), протокол: [protocol/README.md](protocol/README.md).
