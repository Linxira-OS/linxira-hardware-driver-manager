from __future__ import annotations

import hashlib
import json
import re
import subprocess
from typing import Any, Callable


DETECTOR = "/usr/bin/linxira-hwd-detector"
DETECTOR_NAME = "linxira-hwd-detector"
DETECTOR_SCHEMA_VERSION = 1
DETECTOR_TIMEOUT_SECONDS = 10
MAX_OUTPUT_BYTES = 1024 * 1024
KNOWN_PROFILE_IDS = frozenset(
    {
        "cpu.amd",
        "cpu.intel",
        "graphics.amd",
        "graphics.hybrid",
        "graphics.intel",
        "graphics.nvidia",
        "vm.hyperv",
        "vm.qemu",
        "vm.virtualbox",
        "vm.vmware",
        "vm.xen",
    }
)
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")


class DetectorError(RuntimeError):
    pass


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DetectorError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _object(value: Any, name: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DetectorError(f"{name} must be an object")
    missing = keys - value.keys()
    extra = value.keys() - keys
    if missing or extra:
        raise DetectorError(f"{name} keys invalid; missing={sorted(missing)}, extra={sorted(extra)}")
    return value


def _nullable_string(value: Any, name: str) -> None:
    if value is not None and not isinstance(value, str):
        raise DetectorError(f"{name} must be a string or null")


def parse_detector_json(raw: str) -> dict[str, Any]:
    try:
        document = json.loads(raw, object_pairs_hook=_reject_duplicates)
    except DetectorError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise DetectorError(f"invalid detector JSON: {exc}") from exc

    root = _object(document, "root", {"schema_version", "detector", "evidence", "profile_ids", "warnings"})
    if type(root["schema_version"]) is not int or root["schema_version"] != DETECTOR_SCHEMA_VERSION:
        raise DetectorError("unsupported detector schema_version")
    metadata = _object(root["detector"], "detector", {"name", "version", "upstream_chwd"})
    if metadata["name"] != DETECTOR_NAME:
        raise DetectorError("unexpected detector name")
    if not isinstance(metadata["version"], str) or not SEMVER.fullmatch(metadata["version"]):
        raise DetectorError("invalid detector version")
    if not isinstance(metadata["upstream_chwd"], str) or not SEMVER.fullmatch(metadata["upstream_chwd"]):
        raise DetectorError("invalid upstream CHWD version")

    evidence = _object(root["evidence"], "evidence", {"pci", "dmi", "cpu", "virtualization"})
    if not isinstance(evidence["pci"], list):
        raise DetectorError("evidence.pci must be an array")
    for index, item in enumerate(evidence["pci"]):
        device = _object(item, f"evidence.pci[{index}]", {"bus_id", "class_id", "vendor_id", "device_id"})
        if not all(isinstance(value, str) for value in device.values()):
            raise DetectorError(f"evidence.pci[{index}] values must be strings")
    dmi = _object(evidence["dmi"], "evidence.dmi", {"system_vendor", "product_name", "chassis_type"})
    cpu = _object(evidence["cpu"], "evidence.cpu", {"vendor", "family", "model"})
    for key, value in dmi.items():
        _nullable_string(value, f"evidence.dmi.{key}")
    for key, value in cpu.items():
        _nullable_string(value, f"evidence.cpu.{key}")
    _nullable_string(evidence["virtualization"], "evidence.virtualization")

    profiles = root["profile_ids"]
    if not isinstance(profiles, list) or not all(isinstance(item, str) for item in profiles):
        raise DetectorError("profile_ids must be an array of strings")
    if len(profiles) != len(set(profiles)) or profiles != sorted(profiles):
        raise DetectorError("profile_ids must be sorted and unique")
    unknown = set(profiles) - KNOWN_PROFILE_IDS
    if unknown:
        raise DetectorError(f"unknown detector profile IDs: {sorted(unknown)}")
    if not isinstance(root["warnings"], list):
        raise DetectorError("warnings must be an array")
    for index, item in enumerate(root["warnings"]):
        warning = _object(item, f"warnings[{index}]", {"source", "message"})
        if not all(isinstance(value, str) for value in warning.values()):
            raise DetectorError(f"warnings[{index}] values must be strings")
    return root


def run_detector(
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[dict[str, Any], str]:
    try:
        result = runner(
            [DETECTOR],
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=DETECTOR_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise DetectorError("hardware detector timed out") from exc
    except OSError as exc:
        raise DetectorError(f"hardware detector unavailable: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or "").strip()[:300]
        raise DetectorError(f"hardware detector failed with status {result.returncode}: {detail}")
    raw = result.stdout or ""
    if len(raw.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise DetectorError("hardware detector output exceeded size limit")
    return parse_detector_json(raw), hashlib.sha256(raw.encode("utf-8")).hexdigest()
