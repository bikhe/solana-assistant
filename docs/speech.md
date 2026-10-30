# Речь: распознавание и синтез (WP2)

## Движки

| Что | Движок | Языки | Где работает | Установка |
| --- | --- | --- | --- | --- |
| STT | faster-whisper (`faster-whisper`) | ru, en | CPU (int8), CUDA | `uv sync --extra faster-whisper` |
| STT | whisper.cpp (`whisper.cpp`) | ru, en | Vulkan (AMD), Metal, CPU | бинарник `whisper-server`, см. ниже |
| STT | GigaAM v3 (`gigaam`) | ru | CPU (ONNX) | `uv sync --extra gigaam` |
| STT | облако (`openai`) | ru, en | OpenAI-совместимый `/audio/transcriptions` | ключ `openai` в keyring |
| TTS | Silero v4 (`silero`) | ru | CPU (PyTorch) | `uv sync --extra silero` |
| TTS | Piper (`piper`) | en, ru | CPU (ONNX) | `uv sync --extra piper` |
| TTS | облако (`openai`) | ru, en | OpenAI-совместимый `/audio/speech` | ключ `openai` в keyring |

Всё сразу: `uv sync --extra speech`. В CI и тестах эти пакеты не нужны: движки подменяются заглушками.

С `tts_provider = "silero"` русский читает Silero, английский Piper (если голос скачан).

## Модели

Модели скачиваются в папку данных пользователя (`models/<id>/`) через `models.download` с событиями `download.progress`. Каталог в `core/solana_core/models/catalog.py`. Докачка после обрыва работает. SHA-256 проверяется по закреплённому хешу или по хешу, который сообщает Hugging Face; результат пишется в `manifest.json`, `ModelManager.verify()` проверяет его повторно.

`recommend_stt()` выбирает модель под железо: CUDA → faster-whisper large-v3-turbo; Vulkan или Metal и есть `whisper-server` → whisper.cpp large-v3-turbo q5; иначе faster-whisper small на CPU (base на слабых машинах).

## whisper.cpp с Vulkan (RX 6600)

Нужен `whisper-server`, собранный с Vulkan:

```sh
git clone https://github.com/ggml-org/whisper.cpp && cd whisper.cpp
cmake -B build -DGGML_VULKAN=1 && cmake --build build -j --config Release
```

Положи `build/bin/whisper-server` в `PATH`, в `<папка данных>/solana-assistant/bin/` или укажи путь в `SOLANA_WHISPER_SERVER`. Core сам запускает сервер на свободном порту.

## Лицензии

- Веса Silero TTS распространяются под CC BY-NC-SA 4.0 (только некоммерческое использование). Мы их не включаем в сборку, пользователь скачивает их сам.
- `piper-tts` 1.3+ под GPL-3.0 (из-за espeak-ng), поэтому это необязательный extra, а не зависимость по умолчанию. Лицензии голосов Piper разные, смотри `MODEL_CARD` у голоса.
- faster-whisper, whisper.cpp, Whisper, GigaAM и onnx-asr под MIT.

## Замеры

```sh
uv run python scripts/bench_speech.py --download
uv run python scripts/bench_speech.py --wav моя_фраза.wav
```

Скрипт печатает Markdown-таблицу: задержку STT на фразе около 5 с и время до первого звука TTS.
