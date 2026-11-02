"""Unit tests of the voice pipeline parts: end of phrase, commands, auto-pause probes and
the runner that builds the real pipeline."""

from __future__ import annotations

import asyncio
import json
import plistlib
from pathlib import Path

import pytest

from solana_core.config import ConfigStore, MemorySecretStore
from solana_core.pc.common import CommandResult
from solana_core.pipeline import autopause, factory
from solana_core.pipeline.autopause import (
    AutoPause,
    FakePauseProbe,
    LinuxCall,
    LinuxScreenLock,
    MacScreenLock,
    PauseProbe,
    WindowsCall,
    linux_recording_apps,
    macos_screen_locked,
    windows_mic_users,
)
from solana_core.pipeline.commands import (
    is_cancel,
    is_question,
    is_stop,
    normalize,
    strip_wake_word,
)
from solana_core.pipeline.endpoint import Endpointer, EndReason
from solana_core.server.core import Core
from tests.fake_runner import FakeRunner

# ---- end of phrase ----


def feed(ep: Endpointer, pattern: list[tuple[bool, int]]) -> tuple[EndReason | None, int]:
    """Push (is_speech, frames) runs; return the reason and the frame it fired on."""
    for speech, count in pattern:
        for _ in range(count):
            if reason := ep.push(speech):
                return reason, ep.frames
    return None, ep.frames


def test_endpointer_ends_after_the_configured_silence() -> None:
    ep = Endpointer(end_silence_ms=1000)
    reason, at = feed(ep, [(False, 10), (True, 50), (False, 100)])
    assert reason is EndReason.SILENCE
    assert at == 10 + 50 + 50  # 50 frames of 20 ms = 1 s


def test_endpointer_short_pause_does_not_end_the_phrase() -> None:
    ep = Endpointer(end_silence_ms=1000)
    reason, _ = feed(ep, [(True, 20), (False, 40), (True, 20), (False, 10)])
    assert reason is None


def test_endpointer_caps_a_command_at_15_seconds() -> None:
    ep = Endpointer()
    reason, at = feed(ep, [(False, 5), (True, 2000)])
    assert reason is EndReason.MAX_LENGTH
    assert at == 5 + 750  # 15 s of 20 ms frames


def test_endpointer_gives_up_without_speech() -> None:
    ep = Endpointer(start_timeout_ms=5000)
    reason, at = feed(ep, [(False, 1000)])
    assert reason is EndReason.NO_SPEECH and at == 250


def test_endpointer_ignores_a_click() -> None:
    ep = Endpointer(start_timeout_ms=1000, min_speech_ms=60)
    reason, _ = feed(ep, [(True, 2), (False, 100)])
    assert reason is EndReason.NO_SPEECH


# ---- stop, cancel, questions ----


@pytest.mark.parametrize(
    "text", ["Стоп", "стоп!", "Стоп, стоп.", "хватит", "Солана, стоп", "Эй, Солана, хватит", "Stop"]
)
def test_stop_words(text: str) -> None:
    assert is_stop(text)
    assert is_cancel(text)


@pytest.mark.parametrize("text", ["Отмена", "не надо", "Уже не надо.", "забудь", "never mind"])
def test_cancel_words(text: str) -> None:
    assert is_cancel(text)
    assert not is_stop(text)


@pytest.mark.parametrize(
    "text", ["стоп-кран это что", "не надо было так делать", "отмени будильник на семь", ""]
)
def test_longer_phrases_are_commands(text: str) -> None:
    assert not is_stop(text)
    assert not is_cancel(text)


def test_normalize_and_strip_wake_word() -> None:
    assert normalize("Эй, Солана! Какая погода?") == "какая погода"
    assert normalize("лана какая погода") == "какая погода"
    assert strip_wake_word("Эй, Солана, какая погода?") == "какая погода?"
    assert strip_wake_word("Солана какая погода") == "какая погода"
    assert strip_wake_word("Какая погода") == "Какая погода"


@pytest.mark.parametrize(
    ("answer", "question"),
    [
        ("Для какого города?", True),
        ("Хорошо. Что-нибудь ещё?»", True),
        ("Готово.", False),
        ("Что? Ладно, сделала.", False),
        ("", False),
    ],
)
def test_is_question(answer: str, question: bool) -> None:
    assert is_question(answer) is question


# ---- auto-pause probes ----


async def test_linux_screen_lock_reads_locked_hint() -> None:
    runner = FakeRunner({"loginctl show-session 7 -p LockedHint": "LockedHint=yes\n"})
    assert await LinuxScreenLock(runner, session="7").active()
    runner.replies = {"loginctl": "LockedHint=no\n"}
    assert not await LinuxScreenLock(runner, session="7").active()


PACTL = """Source Output #41
\tDriver: protocol-native.c
\tProperties:
\t\tapplication.name = "solana-core"
\t\tapplication.process.id = "1000"
Source Output #42
\tProperties:
\t\tapplication.name = "Telegram Desktop"
\t\tapplication.process.id = "2000"
Source Output #43
\tProperties:
\t\tapplication.name = "PulseAudio Volume Control"
\t\tapplication.process.id = "3000"
"""


def test_linux_recording_apps_skip_ourselves_and_mixers() -> None:
    assert linux_recording_apps(PACTL, own_pid=1000) == ["Telegram Desktop"]
    assert linux_recording_apps(PACTL.split("Source Output #42")[0], own_pid=1000) == []
    assert linux_recording_apps("", own_pid=1) == []


async def test_linux_call_probe() -> None:
    assert await LinuxCall(FakeRunner({"pactl": PACTL}), own_pid=1000).active()
    assert not await LinuxCall(FakeRunner({"pactl": ""}), own_pid=1000).active()


def test_macos_screen_locked_parses_ioreg() -> None:
    locked = plistlib.dumps({"IOConsoleUsers": [{"CGSSessionScreenIsLocked": True}]})
    unlocked = plistlib.dumps({"IOConsoleUsers": [{"kCGSSessionOnConsoleKey": True}]})
    assert macos_screen_locked(locked)
    assert not macos_screen_locked(unlocked)
    assert not macos_screen_locked(plistlib.dumps({}))


async def test_macos_probe_uses_ioreg() -> None:
    plist = plistlib.dumps({"IOConsoleUsers": [{"CGSSessionScreenIsLocked": True}]}).decode()
    runner = FakeRunner({"ioreg -n Root -d1 -a": plist})
    assert await MacScreenLock(runner).active()


def test_windows_mic_users() -> None:
    entries = [
        ("C:#Program Files#Zoom#bin#Zoom.exe", 133, 0),  # recording now
        ("C:#Python312#python.exe", 140, 0),  # that is us
        ("Microsoft.WindowsSoundRecorder_8wekyb3d8bbwe", 120, 125),  # finished
        ("C:#Tools#never.exe", 0, 0),  # never used
    ]
    assert windows_mic_users(entries, own_exe=r"C:\Python312\python.exe") == [
        "C:#Program Files#Zoom#bin#Zoom.exe"
    ]


async def test_windows_call_probe_with_a_reader() -> None:
    probe = WindowsCall(lambda: [("Telegram.exe", 1, 0)], own_exe="solana-core.exe")
    assert await probe.active()


class Broken(PauseProbe):
    reason = "broken"

    def __init__(self) -> None:
        self.calls = 0

    async def active(self) -> bool:
        self.calls += 1
        raise OSError("loginctl: not found")


async def test_auto_pause_drops_probes_that_cannot_work() -> None:
    broken, locked = Broken(), FakePauseProbe("screen_locked", value=False)
    pause = AutoPause([broken, locked])
    assert await pause.check() is None
    locked.value = True
    assert await pause.check() == "screen_locked"
    assert broken.calls == 1
    assert pause.probes == [locked]


async def test_failed_command_disables_a_probe() -> None:
    runner = FakeRunner({"pactl": CommandResult(1, "", "Connection refused")})
    pause = AutoPause([LinuxCall(runner, own_pid=1)])
    assert await pause.check() is None
    assert pause.probes == []


def test_default_probes_match_the_platform() -> None:
    probes = autopause.default_probes()
    assert probes and all(isinstance(p, PauseProbe) for p in probes)


# ---- running the real pipeline ----


async def test_run_voice_reports_a_missing_model_and_retries_on_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = Core(ConfigStore(tmp_path / "config.toml"), MemorySecretStore())
    attempts: list[str] = []

    async def failing_build(core: Core, *args: object) -> object:
        attempts.append(core.config.settings.voice.stt_provider)
        raise RuntimeError("модель не скачана")

    monkeypatch.setattr(factory, "build_pipeline", failing_build)
    monkeypatch.setattr(factory, "POLL_S", 0.01)
    queue = core.bus.subscribe()
    task = asyncio.create_task(factory.run_voice(core))
    await asyncio.sleep(0.05)
    core.config.update({"voice": {"stt_provider": "gigaam"}})
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert attempts == ["faster-whisper", "gigaam"]
    errors = [json.loads(queue.get_nowait()) for _ in range(queue.qsize())]
    assert [e["params"]["code"] for e in errors] == ["voice_unavailable"]  # said once
    assert "модель не скачана" in errors[0]["params"]["message"]


def test_rebuild_key_ignores_live_settings(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    key = factory.rebuild_key(store.settings)
    store.update({"voice": {"end_of_speech_ms": 1500, "wake_sensitivity": 0.7}})
    assert factory.rebuild_key(store.settings) == key
    store.update({"voice": {"output_device": "USB"}})
    assert factory.rebuild_key(store.settings) != key
