"""Generate pydantic models from protocol/ipc.schema.json.

Run from core/: ``uv run python scripts/gen_protocol.py``.
CI runs it and fails if the generated file differs from the committed one.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent
SCHEMA = CORE.parent / "protocol" / "ipc.schema.json"
OUTPUT = CORE / "solana_core" / "protocol" / "generated.py"


def main() -> int:
    cmd = [
        "datamodel-codegen",
        "--input",
        str(SCHEMA),
        "--input-file-type",
        "jsonschema",
        "--output",
        str(OUTPUT),
        "--output-model-type",
        "pydantic_v2.BaseModel",
        "--target-python-version",
        "3.12",
        "--use-standard-collections",
        "--use-union-operator",
        "--use-double-quotes",
        "--use-schema-description",
        "--field-constraints",
        "--enum-field-as-literal",
        "all",
        "--collapse-root-models",
        "--disable-timestamp",
        "--custom-file-header",
        "# Generated from protocol/ipc.schema.json by scripts/gen_protocol.py. Do not edit.",
    ]
    return subprocess.call(cmd, cwd=CORE)


if __name__ == "__main__":
    sys.exit(main())
