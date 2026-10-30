# solana-core

Python-ядро ассистента Solana. Запускается приложением как дочерний процесс и слушает WebSocket на `127.0.0.1`.

```sh
uv sync
uv run solana-core --help
uv run solana-core --fake --port 8765 --token dev   # демо-сценарий без микрофона
uv run pytest -q
```

Структура и правила: [CLAUDE.md](../CLAUDE.md).
