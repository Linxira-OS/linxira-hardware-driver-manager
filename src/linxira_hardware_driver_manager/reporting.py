from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .detector import run_detector
from .policy import POLICY_BY_ID, Policy, recommendations
from .state import SUPPORTED_KERNELS, collect_system_state


REPORT_SCHEMA = "org.linxira.hardware-driver-report.v1"
PLAN_SCHEMA = "org.linxira.hardware-driver-plan.v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_report() -> dict[str, Any]:
    detector, digest = run_detector()
    state = collect_system_state()
    suggested = recommendations(detector["profile_ids"])
    return {
        "schema": REPORT_SCHEMA,
        "generatedAt": _now(),
        "detector": {
            "schemaVersion": detector["schema_version"],
            "metadata": detector["detector"],
            "sha256": digest,
            "profileIds": detector["profile_ids"],
            "warnings": detector["warnings"],
        },
        "recommendations": [
            {
                "policyId": policy.id,
                "title": policy.title,
                "driverModel": policy.driver_model,
                "license": policy.license,
                "reviewRequired": policy.requires_review,
                "available": policy.available,
                "unavailableReason": policy.unavailable_reason,
                "reasonFactId": policy.fact_id,
            }
            for policy in suggested
        ],
        "installedState": state,
        "warnings": state["warnings"],
        "blockers": [],
    }


def _kernel_predicates(state: dict[str, Any], required: bool) -> list[dict[str, Any]]:
    found = {item["package"] for item in state["kernels"]}
    packages = state["packages"]
    predicates = []
    for kernel in SUPPORTED_KERNELS:
        header = f"{kernel}-headers"
        predicates.append(
            {
                "kernelPackage": kernel,
                "kernelPresent": kernel in found and packages[kernel]["installed"],
                "headerPackage": header,
                "headerPresent": packages[header]["installed"],
                "required": required,
            }
        )
    return predicates


def _dkms_predicates(state: dict[str, Any], required: bool) -> list[dict[str, Any]]:
    predicates = []
    by_package = {item["package"]: item for item in state["kernels"]}
    for package in SUPPORTED_KERNELS:
        kernel = by_package.get(package)
        release = kernel["release"] if kernel else None
        installed = release is not None and any(
            item["kernelRelease"] == release and item["status"] == "installed"
            for item in state["dkms"]
        )
        predicates.append(
            {
                "kernelPackage": package,
                "kernelRelease": release,
                "expectedStatus": "installed",
                "satisfied": installed,
                "required": required,
            }
        )
    return predicates


def build_plan(report: dict[str, Any], policy_id: str) -> dict[str, Any]:
    policy: Policy = POLICY_BY_ID[policy_id]
    facts = report["detector"]["profileIds"]
    matches = policy.fact_id in facts
    state = report["installedState"]
    kernel_predicates = _kernel_predicates(state, policy.requires_dkms)
    missing_kernels = [item["kernelPackage"] for item in kernel_predicates if item["required"] and not item["kernelPresent"]]
    warnings = list(report["warnings"])
    blockers = [f"Required supported kernel is not installed: {kernel}" for kernel in missing_kernels]
    if policy.requires_review:
        warnings.append("NVIDIA open/proprietary support is not inferred from PCI device IDs; review and explicit choice are required.")
    if not policy.available:
        blockers.append(policy.unavailable_reason or "The selected fixed policy is unavailable.")
    if not matches:
        blockers.append(f"Detector fact {policy.fact_id} is absent.")
    missing_headers = [item["headerPackage"] for item in kernel_predicates if item["required"] and not item["headerPresent"]]
    if missing_headers:
        warnings.append("Matching headers are currently missing and are included in the fixed package plan: " + ", ".join(missing_headers))
    dkms_predicates = _dkms_predicates(state, policy.requires_dkms)
    driver_installed = policy.requires_dkms and state["packages"][policy.packages[0]]["installed"]
    if driver_installed and not all(item["satisfied"] for item in dkms_predicates):
        blockers.append("The installed DKMS driver is not built successfully for every supported kernel.")
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "generatedAt": _now(),
        "detector": report["detector"],
        "policy": {
            "id": policy.id,
            "reasonFactId": policy.fact_id,
            "packages": list(policy.packages),
            "driverModel": policy.driver_model,
            "license": policy.license,
            "reviewRequired": policy.requires_review,
            "available": policy.available,
            "unavailableReason": policy.unavailable_reason,
        },
        "validation": {
            "supportedKernelPackages": list(SUPPORTED_KERNELS),
            "kernelHeaders": kernel_predicates,
            "dkms": dkms_predicates,
        },
        "effects": {
            "initramfsRegenerationExpected": policy.requires_dkms,
            "rebootExpected": policy.driver_model != "guest",
            "serviceChanges": [],
            "repositoryChanges": list(policy.repository_changes),
        },
        "warnings": warnings,
        "blockers": blockers,
        "applicable": matches and not blockers,
        "apply": {"implemented": False, "result": "backend-not-ready"},
    }
    canonical = json.dumps(plan, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    plan["planSha256"] = hashlib.sha256(canonical).hexdigest()
    return plan


def create_plan(policy_id: str) -> dict[str, Any]:
    return build_plan(build_report(), policy_id)


def plan_directory() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "linxira" / "hardware-driver-manager" / "plans"


def save_plan_atomic(plan: dict[str, Any], directory: Path | None = None) -> Path:
    target_dir = directory or plan_directory()
    if target_dir.is_symlink():
        raise RuntimeError("plan directory must not be a symlink")
    target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not target_dir.is_dir() or target_dir.is_symlink():
        raise RuntimeError("plan path is not a secure directory")
    os.chmod(target_dir, 0o700)
    target = target_dir / f"{plan['planSha256']}.json"
    payload = json.dumps(plan, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".plan-", suffix=".tmp", dir=target_dir)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
        if hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return target
