# brain: LLM и диалог (WP3)

| Файл | Что делает |
| --- | --- |
| `base.py` | Контракт `LLMProvider` и `FakeLLM` (из WP0, не менять в WP-пакетах) |
| `anthropic.py` | Claude через Messages API: стриминг, tool use |
| `openai_compat.py` | OpenAI-совместимый Chat Completions: OpenAI, OpenRouter, Ollama, LM Studio, llama.cpp. Прячет `<think>…</think>` у Qwen3 и DeepSeek-R1 |
| `router.py` | Режимы `cloud` / `local` / `hybrid`, откат на локальную модель без сети, смена провайдера без перезапуска |
| `fast.py` | Частые команды без LLM: «громче», «пауза», «открой …» |
| `dialog.py` | Персона, окно истории, цикл вызова инструментов с лимитом шагов |
| `prompts.py` | Системный промпт «Соланы» (ru, en) |

## Провайдеры и ключи

`brain.cloud_provider` и `brain.local_provider` в настройках:

| Значение | Адрес по умолчанию | Ключ в keyring | Переменная окружения |
| --- | --- | --- | --- |
| `anthropic` | api.anthropic.com | `anthropic_api_key` | `ANTHROPIC_API_KEY` |
| `openai` | api.openai.com/v1 | `openai_api_key` | `OPENAI_API_KEY` |
| `openrouter` | openrouter.ai/api/v1 | `openrouter_api_key` | `OPENROUTER_API_KEY` |
| `openai-compatible` | `*_base_url` из настроек | `openai_compatible_api_key` | |
| `ollama` | 127.0.0.1:11434/v1 | | |
| `lmstudio` | 127.0.0.1:1234/v1 | | |
| `llamacpp` | 127.0.0.1:8080/v1 | | |

## Ручная проверка

```sh
cd core
uv run python -m solana_core.brain --set-key anthropic --mode cloud
uv run python -m solana_core.brain --mode local --local-model qwen3:8b
uv run python -m solana_core.brain --mode hybrid
```

Инструменты ПК там фейковые: вызовы печатаются, с компьютером ничего не происходит. После ответа печатается, какой провайдер ответил и через сколько пришло первое событие.

## Быстрые команды

Срабатывают, только если нужный инструмент зарегистрирован и включён; иначе фраза уходит в LLM. Имена согласованы с WP5: `pc.volume_set {level}`, `pc.volume_change {delta}`, `pc.mute {muted}`, `pc.media {action}`, `pc.app_open {name}`, `pc.app_close {name}`, `pc.url_open {url}`, `pc.web_search {query}`.
