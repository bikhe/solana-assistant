"""``python -m wakeword <command>``: generate, train, evaluate, record."""

from __future__ import annotations

import logging
import sys

COMMANDS = ("generate", "train", "evaluate", "record")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"usage: python -m wakeword {{{','.join(COMMANDS)}}} [--help]")
        raise SystemExit(2)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    command, argv = sys.argv[1], sys.argv[2:]
    if command == "generate":
        from wakeword.generate import main as run
    elif command == "train":
        from wakeword.train import main as run
    elif command == "evaluate":
        from wakeword.evaluate import main as run
    else:
        from wakeword.record import main as run
    run(argv)


if __name__ == "__main__":
    main()
