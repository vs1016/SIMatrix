from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


APP_NAME = "RTG One-Click"
PAYLOAD_DIR_NAME = "payload"
RUNTIME_DIR_NAME = "runtime"
VERSION_FILE_NAME = "payload.version"


def resource_root() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")).resolve()
    return Path(__file__).resolve().parent


def bundled_payload_root() -> Path:
    return resource_root() / PAYLOAD_DIR_NAME


def bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def runtime_root() -> Path:
    return bundle_root() / RUNTIME_DIR_NAME


def read_version(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def replace_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def copy_missing_tree(source: Path, destination: Path) -> None:
    for source_path in source.rglob("*"):
        relative_path = source_path.relative_to(source)
        destination_path = destination / relative_path
        if source_path.is_dir():
            destination_path.mkdir(parents=True, exist_ok=True)
            continue
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if not destination_path.exists():
            shutil.copy2(source_path, destination_path)


def sync_payload() -> Path:
    source_root = bundled_payload_root()
    destination_root = runtime_root()
    bundled_version = read_version(source_root / VERSION_FILE_NAME)
    installed_version = read_version(destination_root / VERSION_FILE_NAME)

    if (
        bundled_version
        and bundled_version == installed_version
        and (destination_root / "123-clean-start-open-rtg.bat").exists()
    ):
        return destination_root

    print(f"[{APP_NAME}] Preparing bundled runtime files...")
    destination_root.mkdir(parents=True, exist_ok=True)
    if installed_version and installed_version != bundled_version:
        existing_venv = destination_root / ".venv"
        if existing_venv.exists():
            shutil.rmtree(existing_venv, ignore_errors=True)

    for source_item in source_root.iterdir():
        if source_item.name == VERSION_FILE_NAME:
            continue
        destination_item = destination_root / source_item.name
        if source_item.is_dir():
            if source_item.name == "data":
                destination_item.mkdir(parents=True, exist_ok=True)
                copy_missing_tree(source_item, destination_item)
            else:
                replace_tree(source_item, destination_item)
        else:
            shutil.copy2(source_item, destination_item)

    if bundled_version:
        (destination_root / VERSION_FILE_NAME).write_text(
            bundled_version,
            encoding="utf-8",
        )
    return destination_root


def launch_runtime(target_root: Path, arguments: list[str]) -> int:
    script_path = target_root / "123-clean-start-open-rtg.bat"
    if not script_path.exists():
        print(f"[{APP_NAME}] Startup script was not found: {script_path}")
        return 1

    environment = os.environ.copy()
    environment.setdefault("PYTHONUTF8", "1")
    environment.setdefault("PYTHONIOENCODING", "utf-8")
    if "--no-browser" in arguments:
        environment["RTG_SKIP_BROWSER"] = "1"

    if "--prepare-only" in arguments:
        print(f"[{APP_NAME}] Runtime prepared at {target_root}")
        return 0

    return subprocess.call(
        ["cmd.exe", "/c", str(script_path)],
        cwd=target_root,
        env=environment,
    )


def main() -> int:
    try:
        target_root = sync_payload()
    except Exception as exc:  # pragma: no cover - bootstrap safety net
        print(f"[{APP_NAME}] Failed while preparing the runtime: {exc}")
        return 1
    return launch_runtime(target_root, sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
