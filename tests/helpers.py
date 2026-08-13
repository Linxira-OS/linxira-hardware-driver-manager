from __future__ import annotations

import json
from pathlib import Path
import subprocess


def detector_document(*profile_ids: str) -> dict:
    return {
        "schema_version": 1,
        "detector": {"name": "linxira-hwd-detector", "version": "0.1.0", "upstream_chwd": "1.23.0"},
        "evidence": {
            "pci": [],
            "dmi": {"system_vendor": None, "product_name": None, "chassis_type": None},
            "cpu": {"vendor": None, "family": None, "model": None},
            "virtualization": None,
        },
        "profile_ids": sorted(profile_ids),
        "warnings": [],
    }


def detector_json(*profile_ids: str) -> str:
    return json.dumps(detector_document(*profile_ids))


class FixedRunner:
    def __init__(self, installed: set[str] | None = None, dkms: str = "", release: str = "6.12.1-arch1-1"):
        self.installed = installed or set()
        self.dkms = dkms
        self.release = release
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        self.calls.append((argv, kwargs))
        executable = Path(argv[0]).name
        if executable == "uname":
            return subprocess.CompletedProcess(argv, 0, self.release + "\n", "")
        if executable == "dkms":
            return subprocess.CompletedProcess(argv, 0, self.dkms, "")
        if executable == "pacman":
            package = argv[2]
            if package in self.installed:
                return subprocess.CompletedProcess(argv, 0, f"{package} 1.0-1\n", "")
            return subprocess.CompletedProcess(argv, 1, "", f"error: package '{package}' was not found")
        raise AssertionError(f"unexpected command: {argv}")


def write_state_files(root: Path, kernels: tuple[tuple[str, str], ...] = (("linux", "6.12.1-arch1-1"),)) -> dict:
    modules = root / "modules"
    boot = root / "boot"
    modules.mkdir()
    boot.mkdir()
    for package, release in kernels:
        target = modules / release
        target.mkdir()
        (target / "pkgbase").write_text(package + "\n", encoding="utf-8")
    proc_modules = root / "proc-modules"
    proc_modules.write_text("nvidia 1 0 - Live 0x0\ni915 1 0 - Live 0x0\n", encoding="utf-8")
    uptime = root / "uptime"
    uptime.write_text("100.0 50.0\n", encoding="utf-8")
    return {"module_root": modules, "boot_root": boot, "proc_modules": proc_modules, "proc_uptime": uptime, "reboot_marker": root / "reboot-required"}


def report_for(profile_ids: list[str], state: dict) -> dict:
    detector = detector_document(*profile_ids)
    return {
        "schema": "org.linxira.hardware-driver-report.v1",
        "generatedAt": "2026-07-21T00:00:00+00:00",
        "detector": {
            "schemaVersion": 1,
            "metadata": detector["detector"],
            "sha256": "a" * 64,
            "profileIds": detector["profile_ids"],
            "warnings": [],
        },
        "recommendations": [],
        "installedState": state,
        "warnings": state["warnings"],
        "blockers": [],
    }
