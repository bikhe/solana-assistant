# solana-app

Оболочка на Tauri 2 + React + Tailwind CSS.

```sh
pnpm install
pnpm tauri dev    # окно + core из исходников (fake-режим по умолчанию, SOLANA_FAKE=0 для настоящего)
```

Только веб-часть в браузере, без Tauri:

```sh
cd ../core && uv run solana-core --fake --port 8765 --token dev
cd ../app && pnpm dev   # http://localhost:1420/?port=8765&token=dev
```
