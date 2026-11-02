# Сборка и релизы

Как Solana превращается в установщики, как выпустить версию и что увидит пользователь при первом запуске неподписанной сборки.

## Что внутри установщика

- Приложение Tauri (`app/`) и core (`core/`), собранный PyInstaller в один исполняемый файл `solana-core`. Tauri кладёт его рядом с приложением как sidecar, и приложение запускает его при старте.
- Моделей в установщике нет. Wake word, распознавание, синтез и локальная LLM скачиваются мастером первого запуска (`models.download`), поэтому установщик весит десятки мегабайт, а не гигабайты.

| ОС | Файлы | Автообновление |
| --- | --- | --- |
| Windows | `Solana_<версия>_x64-setup.exe` (NSIS, русский и английский), `Solana_<версия>_x64_en-US.msi` | да |
| Linux | `.AppImage`, `.deb`, `.rpm` | только AppImage; deb и rpm обновляются новым пакетом |
| macOS | `.dmg` для Apple Silicon | да |

Mac на Intel пока не собираем: PyInstaller не умеет собирать под другую архитектуру, а Intel-раннеры GitHub уходят.

## Собрать локально

```sh
cd core
uv sync
uv run python packaging/build_sidecar.py --smoke   # app/src-tauri/binaries/solana-core-<triple>
cd ../app
pnpm install
pnpm tauri build --config src-tauri/tauri.release.conf.json
```

Установщики появятся в `app/src-tauri/target/release/bundle/`. Без `--config src-tauri/tauri.release.conf.json` сборка пройдёт, но без core внутри: так устроено специально, чтобы `pnpm tauri dev` и `cargo clippy` не требовали собранного sidecar.

`--smoke` запускает собранный бинарник в fake-режиме, ждёт строку `SOLANA_CORE_READY` и шлёт `ping` по WebSocket. CI делает это на трёх ОС в каждом PR: если новая зависимость ломает сборку в один файл (скрытые импорты, файлы данных), это видно сразу. Если PyInstaller не находит модуль, добавь `--hidden-import` или `--collect-data` в `core/packaging/build_sidecar.py`.

## Выпустить версию

1. Подними версию в `app/src-tauri/tauri.conf.json` (по ней называются установщики и работает автообновление). Для порядка ту же версию ставь в `app/src-tauri/Cargo.toml`, `app/package.json`, `core/pyproject.toml` и `core/solana_core/__init__.py`.
2. Смержи это в `main` и поставь тег: `git tag v0.2.0 && git push origin v0.2.0`. Тег с дефисом (`v0.2.0-beta.1`) станет пре-релизом.
3. Workflow **Release** проверит, что тег совпадает с версией, соберёт установщики на Windows, Linux и macOS и приложит их к черновику релиза.
4. Проверь черновик на странице Releases и нажми **Publish**. Только после этого установленные приложения увидят обновление: они читают `releases/latest/download/latest.json`.

PR, которые меняют `core/packaging/`, `app/src-tauri/` или этот workflow, собирают те же установщики и кладут их в артефакты прогона, ничего не публикуя.

## Ключ автообновления

Tauri принимает только обновления, подписанные вашим ключом. Без ключа релиз всё равно соберётся, просто без автообновления. Настроить один раз:

1. Сгенерируй пару ключей: `cd app && pnpm tauri signer generate -w ~/.tauri/solana.key`. Задай пароль.
2. В репозитории на GitHub, **Settings → Secrets and variables → Actions**:
   - секрет `TAURI_SIGNING_PRIVATE_KEY`: содержимое `~/.tauri/solana.key`;
   - секрет `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`: пароль;
   - переменная (вкладка Variables) `TAURI_UPDATER_PUBKEY`: содержимое `~/.tauri/solana.key.pub`.
3. Сохрани приватный ключ и пароль в менеджере паролей. Публичный ключ зашивается в каждую установленную копию: если потерять приватный, старые копии больше не смогут обновиться сами, и пользователям придётся поставить новую версию вручную.

`core/packaging/release_config.py` включает updater только когда есть и публичный, и приватный ключ, поэтому сборки из форков и PR без секретов не падают. Приложение проверяет обновления при старте и спрашивает: «Доступна новая версия Solana… Обновить / Позже». На Windows установщик ставится в тихом режиме, core перед этим останавливается, потом приложение перезапускается.

## Подпись и предупреждения ОС

Сейчас установщики не подписаны сертификатами Microsoft или Apple. Это бесплатно и работает, но при первом запуске ОС предупреждает.

### Windows: SmartScreen

Окно «Windows защитила ваш компьютер». Нажать **Подробнее → Выполнить в любом случае**. Предупреждение пропадёт, когда у подписанного файла накопится репутация.

Как убрать совсем, от дешёвого к дорогому:

- [SignPath Foundation](https://signpath.org/): бесплатная подпись для open source проектов, подключается к GitHub Actions. Лучший вариант для нас, нужна заявка.
- Azure Trusted Signing: около $10 в месяц, нужна проверка личности или организации.
- Обычный сертификат подписи кода (OV или EV) от удостоверяющего центра: от ~$200 в год, EV сразу снимает SmartScreen.

Подпись подключается в `bundle.windows` (`signCommand` или `certificateThumbprint`) и через секреты workflow. Подписывать нужно и `solana-core.exe`: Tauri подписывает sidecar вместе с приложением, если подпись настроена.

### macOS: Gatekeeper

Сборка подписана ad-hoc (`bundle.macOS.signingIdentity: "-"`), но не нотаризована. Скачанное приложение macOS откроет с сообщением «не удаётся проверить разработчика» или «приложение повреждено». Что делать:

- **Системные настройки → Конфиденциальность и безопасность → Всё равно открыть**, или
- в терминале: `xattr -dr com.apple.quarantine /Applications/Solana.app`.

Чтобы предупреждения не было, нужен Apple Developer Program ($99 в год) и нотаризация. tauri-action делает её сам, если задать секреты `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID` и передать их в шаг сборки. При нотаризации с hardened runtime понадобится файл entitlements с `com.apple.security.device.audio-input` для микрофона.

Запрос доступа к микрофону уже описан в `app/src-tauri/Info.plist` (`NSMicrophoneUsageDescription`): без него macOS молча не даст слушать.

### Linux

Подпись не нужна. AppImage перед запуском: `chmod +x Solana_*.AppImage`. Для трея в GNOME нужно расширение AppIndicator.

## Установка

- **Windows:** запусти `*-setup.exe`. Ставится для текущего пользователя, права администратора не нужны.
- **Linux:** `sudo apt install ./Solana_*.deb`, `sudo dnf install ./Solana-*.rpm` или AppImage без установки.
- **macOS:** открой `.dmg`, перетащи Solana в «Программы», затем см. раздел про Gatekeeper.
