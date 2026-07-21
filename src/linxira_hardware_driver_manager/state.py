from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess
from typing import Any, Callable

from .policy import ALL_PACKAGES


UNAME = "/usr/bin/uname"
PACMAN = "/usr/bin/pacman"
DKMS = "/usr/bin/dkms"
COMMAND_TIMEOUT_SECONDS = 8
SUPPORTED_KERNELS = ("linux", "linux-lts")


def _run(runner: Callable[..., subprocess.CompletedProcess[str]], argv: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return runner(argv, capture_output=True, text=True, check=False, shell=False, timeout=COMMAND_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _timestamp(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def collect_system_state(
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    module_root: Path = Path("/usr/lib/modules"),
    boot_root: Path = Path("/boot"),
    proc_modules: Path = Path("/proc/modules"),
    proc_uptime: Path = Path("/proc/uptime"),
    reboot_marker: Path = Path("/run/reboot-required"),
) -> dict[str, Any]:
    warnings: list[str] = []
    uname = _run(runner, [UNAME, "-r"])
    running_release = uname.stdout.strip() if uname is not None and uname.returncode == 0 else None
    if running_release is None:
        warnings.append("Unable to read the running kernel release.")

    kernels: list[dict[str, Any]] = []
    try:
        pkgbase_paths = sorted(module_root.glob("*/pkgbase"))
    except OSError:
        pkgbase_paths = []
    for path in pkgbase_paths:
        try:
            pkgbase = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if pkgbase in SUPPORTED_KERNELS:
            kernels.append({"package": pkgbase, "release": path.parent.name, "running": path.parent.name == running_release})

    packages: dict[str, dict[str, Any]] = {}
    for package in ALL_PACKAGES:
        result = _run(runner, [PACMAN, "-Q", package])
        installed = result is not None and result.returncode == 0
        version = None
        if installed:
            fields = result.stdout.strip().split(maxsplit=1)
            if len(fields) == 2 and fields[0] == package:
                version = fields[1]
            else:
                installed = False
                warnings.append(f"Unexpected package query output for {package}.")
        elif result is None:
            warnings.append(f"Unable to query package {package}.")
        packages[package] = {"installed": installed, "version": version}

    dkms_result = _run(runner, [DKMS, "status"])
    dkms_lines = [] if dkms_result is None or dkms_result.returncode != 0 else [line.strip() for line in dkms_result.stdout.splitlines() if line.strip()]
    if dkms_result is None or dkms_result.returncode != 0:
        warnings.append("Unable to read DKMS status.")
    dkms = []
    for line in dkms_lines:
        fields = [field.strip() for field in line.split(",")]
        module = fields[0] if fields else ""
        release = fields[1] if len(fields) > 1 else None
        status = fields[-1].split(":", 1)[-1].strip().lower() if len(fields) > 1 else "unknown"
        dkms.append({"module": module, "kernelRelease": release, "status": status, "raw": line})

    initramfs = []
    for kernel in SUPPORTED_KERNELS:
        for fallback in (False, True):
            suffix = "-fallback" if fallback else ""
            path = boot_root / f"initramfs-{kernel}{suffix}.img"
            initramfs.append({"kernel": kernel, "fallback": fallback, "exists": path.is_file(), "modifiedAt": _timestamp(path)})

    try:
        loaded = sorted({line.split()[0] for line in proc_modules.read_text(encoding="utf-8").splitlines() if line.split()})
    except OSError:
        loaded = []
        warnings.append("Unable to read loaded kernel modules.")
    marker = reboot_marker.exists()
    initramfs_newer_than_boot = False
    try:
        uptime = float(proc_uptime.read_text(encoding="utf-8").split()[0])
        boot_epoch = datetime.now(timezone.utc).timestamp() - uptime
        initramfs_newer_than_boot = any(item["modifiedAt"] and datetime.fromisoformat(item["modifiedAt"]).timestamp() > boot_epoch for item in initramfs)
    except (OSError, ValueError, IndexError):
        pass

    return {
        "runningKernelRelease": running_release,
        "supportedKernels": list(SUPPORTED_KERNELS),
        "kernels": kernels,
        "packages": packages,
        "dkms": dkms,
        "initramfs": initramfs,
        "loadedModules": loaded,
        "reboot": {"required": marker or initramfs_newer_than_boot, "markerPresent": marker, "initramfsNewerThanBoot": initramfs_newer_than_boot},
        "warnings": warnings,
    }
