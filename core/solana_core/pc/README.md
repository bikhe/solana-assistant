# Управление ПК

`get_pc_backend()` из `solana_core.pc` выбирает бэкенд по ОС, `register_pc_tools(registry)` из `solana_core.pc.tools` регистрирует 29 инструментов `pc.*`. Если ОС чего-то не умеет, инструмент отвечает «Не поддерживается на этом компьютере» с причиной, а не падает.

| Группа | Windows | Linux | macOS |
| --- | --- | --- | --- |
| Приложения | ярлыки меню «Пуск», `os.startfile`, WM_CLOSE окнам процесса | `.desktop` из XDG, SIGTERM процессу | `/Applications`, `open -a`, `quit` через AppleScript |
| Окна | Win32 (ctypes) | `wmctrl` (+ `xdotool`), только X11 | System Events, нужен «Универсальный доступ» |
| Громкость | Core Audio (pycaw) | `wpctl` (PipeWire) или `pactl` | `osascript` |
| Медиа | медиаклавиши, SMTC для «что играет» | `playerctl` или MPRIS через `gdbus` | Spotify и Музыка через AppleScript |
| Файлы | поиск по папкам пользователя, `explorer /select` | то же, `xdg-open`, FileManager1 | Spotlight (`mdfind`), `open -R` |
| Корзина, батарея, скриншот | send2trash, psutil, mss | то же, `grim` в Wayland | то же, нужна «Запись экрана» |
| Буфер, уведомления | Win32, toast через PowerShell | `wl-clipboard` / `xclip`, `notify-send` | `pbcopy`, `display notification` |
| Блокировка, сон, выключение | `LockWorkStation`, `SetSuspendState`, `shutdown` | `loginctl`, `systemctl` | `pmset`, System Events |

Безвозвратного удаления файлов нет: только корзина. Перемещение никогда не перезаписывает существующий файл. `pc.file_open` не запускает программы и скрипты.

Для Linux полезно поставить: `sudo apt install wmctrl xdotool playerctl xclip wl-clipboard libnotify-bin` (что есть в системе, то и заработает).
