from __future__ import annotations

import hashlib
import importlib.util
import io
import shutil
import stat
import tarfile
import types
import zipfile
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "setup_third_party_tools.py"


def load_setup_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("setup_third_party_tools", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load setup_third_party_tools module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_tar_gz(archive_path: Path, *, member_name: str, data: bytes) -> None:
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo(name=member_name)
        info.mode = 0o755
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))


def _build_zip(archive_path: Path, *, member_name: str, data: bytes) -> None:
    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, data)


@pytest.mark.parametrize(
    ("sys_platform", "machine", "expected"),
    [
        ("linux", "x86_64", "linux_x86_64"),
        ("darwin", "arm64", "darwin_arm64"),
        ("win32", "AMD64", "windows_x86_64"),
    ],
)
def test_normalized_platform_mapping(sys_platform: str, machine: str, expected: str, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_setup_module()
    monkeypatch.setattr(module.sys, "platform", sys_platform)
    monkeypatch.setattr(module.platform, "machine", lambda: machine)

    assert module._normalized_platform() == expected


def test_install_pmtiles_from_tar_gz(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_setup_module()
    archive_path = tmp_path / "go-pmtiles_1.30.0_Linux_x86_64.tar.gz"
    expected_binary = b"fake-pmtiles-linux"
    _build_tar_gz(
        archive_path,
        member_name="go-pmtiles_1.30.0_Linux_x86_64/pmtiles",
        data=expected_binary,
    )

    sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    config = {
        "version": "1.30.0",
        "assets": {
            "linux_x86_64": {
                "url": "https://example.invalid/go-pmtiles_1.30.0_Linux_x86_64.tar.gz",
                "sha256": sha256,
                "binary": "pmtiles",
            }
        },
    }

    tools_root = tmp_path / "third-party-tools"
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "TOOLS_ROOT", tools_root)
    monkeypatch.setattr(module, "_normalized_platform", lambda: "linux_x86_64")

    def fake_download(_url: str, output_file: Path) -> None:
        shutil.copy2(archive_path, output_file)

    monkeypatch.setattr(module, "_download_file", fake_download)

    module.install_pmtiles(config=config, force=False)

    installed_path = tools_root / "pmtiles" / "1.30.0" / "bin" / "pmtiles"
    assert installed_path.read_bytes() == expected_binary
    assert installed_path.stat().st_mode & stat.S_IXUSR


def test_install_pmtiles_from_zip_windows_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_setup_module()
    archive_path = tmp_path / "go-pmtiles_1.30.0_Windows_x86_64.zip"
    expected_binary = b"fake-pmtiles-windows"
    _build_zip(
        archive_path,
        member_name="go-pmtiles_1.30.0_Windows_x86_64/pmtiles.exe",
        data=expected_binary,
    )

    sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    config = {
        "version": "1.30.0",
        "assets": {
            "windows_x86_64": {
                "url": "https://example.invalid/go-pmtiles_1.30.0_Windows_x86_64.zip",
                "sha256": sha256,
                "binary": "pmtiles.exe",
            }
        },
    }

    tools_root = tmp_path / "third-party-tools"
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "TOOLS_ROOT", tools_root)
    monkeypatch.setattr(module, "_normalized_platform", lambda: "windows_x86_64")

    def fake_download(_url: str, output_file: Path) -> None:
        shutil.copy2(archive_path, output_file)

    monkeypatch.setattr(module, "_download_file", fake_download)

    module.install_pmtiles(config=config, force=False)

    installed_path = tools_root / "pmtiles" / "1.30.0" / "bin" / "pmtiles.exe"
    assert installed_path.read_bytes() == expected_binary


def test_install_pmtiles_raises_on_checksum_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_setup_module()
    archive_path = tmp_path / "go-pmtiles_1.30.0_Linux_x86_64.tar.gz"
    _build_tar_gz(
        archive_path,
        member_name="go-pmtiles_1.30.0_Linux_x86_64/pmtiles",
        data=b"fake-pmtiles-linux",
    )

    config = {
        "version": "1.30.0",
        "assets": {
            "linux_x86_64": {
                "url": "https://example.invalid/go-pmtiles_1.30.0_Linux_x86_64.tar.gz",
                "sha256": "0" * 64,
                "binary": "pmtiles",
            }
        },
    }

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "TOOLS_ROOT", tmp_path / "third-party-tools")
    monkeypatch.setattr(module, "_normalized_platform", lambda: "linux_x86_64")

    def fake_download(_url: str, output_file: Path) -> None:
        shutil.copy2(archive_path, output_file)

    monkeypatch.setattr(module, "_download_file", fake_download)

    with pytest.raises(module.SetupError, match="checksum mismatch"):
        module.install_pmtiles(config=config, force=False)
