"""Write the Tauri config overlay for a release build.

The overlay adds the sidecar (``tauri.release.conf.json``) and, when the updater key pair is set
up, the updater: ``TAURI_UPDATER_PUBKEY`` (public key) and ``TAURI_SIGNING_PRIVATE_KEY`` (the
secret the Tauri CLI signs updates with). Without them the build is unsigned and has no updater.

For a tag build it also checks that the tag matches the app version: ``v0.2.0`` needs
``"version": "0.2.0"`` in ``app/src-tauri/tauri.conf.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

TAURI = Path(__file__).resolve().parents[2] / "app" / "src-tauri"


def overlay(repo: str, pubkey: str | None, signing_key: str | None) -> dict[str, object]:
    config: dict[str, object] = json.loads((TAURI / "tauri.release.conf.json").read_text("utf-8"))
    config.pop("$schema", None)
    if pubkey and signing_key:
        bundle = config.setdefault("bundle", {})
        assert isinstance(bundle, dict)
        bundle["createUpdaterArtifacts"] = True
        config["plugins"] = {
            "updater": {
                "pubkey": pubkey,
                "endpoints": [f"https://github.com/{repo}/releases/latest/download/latest.json"],
                "windows": {"installMode": "passive"},
            }
        }
    return config


def check_tag(tag: str) -> None:
    version = json.loads((TAURI / "tauri.conf.json").read_text("utf-8"))["version"]
    if tag.removeprefix("v") != version:
        sys.exit(f"tag {tag} does not match version {version} in app/src-tauri/tauri.conf.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out", type=Path, default=Path(__file__).resolve().parent / "build" / "tauri.ci.conf.json"
    )
    parser.add_argument("--tag", help="release tag such as v0.2.0")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args()

    if args.tag:
        check_tag(args.tag)
    config = overlay(
        args.repo,
        os.environ.get("TAURI_UPDATER_PUBKEY"),
        os.environ.get("TAURI_SIGNING_PRIVATE_KEY"),
    )
    if "plugins" in config and not args.repo:
        sys.exit("--repo (or $GITHUB_REPOSITORY) is needed for the updater endpoint")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(config, indent=2) + "\n", "utf-8")
    updater = "with updater" if "plugins" in config else "without updater (no signing key)"
    print(f"wrote {args.out} {updater}")


if __name__ == "__main__":
    main()
