#!/usr/bin/env python3
"""Install third-party tooling used by tilemaker."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK_FILE = REPO_ROOT / "third-party-tools.lock.json"
TOOLS_ROOT = REPO_ROOT / "third-party-tools"
TOOL_NAMES = ("tippecanoe", "pmtiles")


class SetupError(RuntimeError):
    """Raised when setup cannot proceed."""


def ensure_command(name: str) -> None:
    if shutil.which(name) is None:
        raise SetupError(f"required command not found on PATH: {name}")


def run_command(cmd: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def load_lock_config() -> dict[str, object]:
    return json.loads(LOCK_FILE.read_text(encoding="utf-8"))


def copy_binaries(source_dir: Path, dest_dir: Path, binaries: list[str]) -> list[Path]:
    installed: list[Path] = []
    missing: list[str] = []
    dest_dir.mkdir(parents=True, exist_ok=True)
    for binary_name in binaries:
        source_path = source_dir / binary_name
        if not source_path.is_file():
            missing.append(binary_name)
            continue
        dest_path = dest_dir / binary_name
        shutil.copy2(source_path, dest_path)
        dest_path.chmod(dest_path.stat().st_mode | 0o111)
        installed.append(dest_path)
    if missing:
        missing_display = ", ".join(sorted(missing))
        raise SetupError(f"missing expected binaries after install: {missing_display}")
    return installed


def _normalized_platform() -> str:
    if sys.platform.startswith("linux"):
        os_name = "linux"
    elif sys.platform == "darwin":
        os_name = "darwin"
    elif sys.platform.startswith(("win32", "cygwin", "msys")):
        os_name = "windows"
    else:
        raise SetupError(f"unsupported platform: {sys.platform}")

    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "x86_64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        raise SetupError(f"unsupported architecture: {machine}")

    return f"{os_name}_{arch}"


def _archive_type_from_name(name: str) -> str:
    if name.endswith(".tar.gz"):
        return "tar.gz"
    if name.endswith(".zip"):
        return "zip"
    raise SetupError(f"unsupported archive format: {name}")


def _download_file(url: str, output_file: Path) -> None:
    with urllib.request.urlopen(url) as response, output_file.open("wb") as output:
        shutil.copyfileobj(response, output)


def _sha256_digest(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as file_obj:
        while chunk := file_obj.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_binary_from_archive(archive_path: Path, *, binary_name: str) -> bytes:
    archive_type = _archive_type_from_name(archive_path.name)

    if archive_type == "tar.gz":
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                if Path(member.name).name != binary_name:
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    break
                return extracted.read()
        raise SetupError(f"binary {binary_name!r} not found in archive {archive_path.name}")

    with zipfile.ZipFile(archive_path) as archive:
        for member_name in archive.namelist():
            if Path(member_name).name != binary_name:
                continue
            with archive.open(member_name) as extracted:
                return extracted.read()
    raise SetupError(f"binary {binary_name!r} not found in archive {archive_path.name}")


def install_tippecanoe(config: dict[str, object], *, force: bool, jobs: int | None) -> None:
    if sys.platform.startswith("win"):
        raise SetupError("tippecanoe source build is not supported by this script on Windows")

    ensure_command("git")
    ensure_command("make")

    repo = str(config["repo"])
    version = str(config["version"])
    binaries = [str(name) for name in config["binaries"]]

    install_root = TOOLS_ROOT / "tippecanoe" / version
    source_root = install_root / "src"
    bin_root = install_root / "bin"
    sentinel = bin_root / "tippecanoe"

    if sentinel.exists() and not force:
        print(f"tippecanoe {version} already installed at {sentinel}")
        return

    if force and install_root.exists():
        shutil.rmtree(install_root)

    install_root.mkdir(parents=True, exist_ok=True)

    if source_root.exists():
        shutil.rmtree(source_root)
    run_command(["git", "clone", "--depth", "1", "--branch", version, repo, str(source_root)])

    build_cmd = ["make"]
    if jobs and jobs > 0:
        build_cmd.extend(["-j", str(jobs)])
    run_command(build_cmd, cwd=source_root)

    installed = copy_binaries(source_root, bin_root, binaries)

    print(f"Installed tippecanoe {version} binaries:")
    for path in installed:
        print(f"- {path.relative_to(REPO_ROOT)}")


def install_pmtiles(config: dict[str, object], *, force: bool) -> None:
    version = str(config["version"])
    platform_id = _normalized_platform()
    assets = config["assets"]  # type: ignore[index]
    if platform_id not in assets:  # type: ignore[operator]
        raise SetupError(f"no pmtiles release configured for platform {platform_id}")
    platform_asset = assets[platform_id]  # type: ignore[index]
    url = str(platform_asset["url"])
    sha256 = str(platform_asset["sha256"]).lower()
    binary_name = str(platform_asset["binary"])

    install_root = TOOLS_ROOT / "pmtiles" / version
    bin_root = install_root / "bin"
    sentinel = bin_root / binary_name

    if sentinel.exists() and not force:
        print(f"pmtiles {version} already installed at {sentinel}")
        return

    if force and install_root.exists():
        shutil.rmtree(install_root)

    install_root.mkdir(parents=True, exist_ok=True)
    bin_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="pmtiles-download-") as tmpdir:
        archive_name = Path(url).name
        archive_path = Path(tmpdir) / archive_name
        _download_file(url, archive_path)

        actual_sha256 = _sha256_digest(archive_path)
        if actual_sha256 != sha256:
            raise SetupError(
                "download checksum mismatch for "
                f"{archive_name}: expected {sha256}, got {actual_sha256}"
            )

        binary_data = _extract_binary_from_archive(archive_path, binary_name=binary_name)
        sentinel.write_bytes(binary_data)
        sentinel.chmod(sentinel.stat().st_mode | 0o111)

    print(f"Installed pmtiles {version} binary:")
    print(f"- {sentinel.relative_to(REPO_ROOT)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install third-party tools for tilemaker")
    parser.add_argument(
        "--tool",
        default="tippecanoe",
        choices=[*TOOL_NAMES, "all"],
        help="Which tool to install (default: tippecanoe)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reinstall even if the tool already exists",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=max((os.cpu_count() or 2) - 1, 1),
        help="Parallel build jobs for make (default: cpu_count - 1)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_lock_config()

    if args.tool == "all":
        tool_names = list(TOOL_NAMES)
    else:
        tool_names = [args.tool]
    for tool_name in tool_names:
        if tool_name == "tippecanoe":
            install_tippecanoe(
                config=config["tippecanoe"],  # type: ignore[index]
                force=args.force,
                jobs=args.jobs,
            )
        elif tool_name == "pmtiles":
            install_pmtiles(
                config=config["pmtiles"],  # type: ignore[index]
                force=args.force,
            )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
