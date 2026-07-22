from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


BUS_NAME = "org.linxira.Components1"
OBJECT_PATH = "/org/linxira/Components1"
INTERFACE = "org.linxira.Components1"
HARDWARE_DIAGNOSIS = "org.linxira.hardware.driver-state-diagnose.v1"


class BackendError(RuntimeError):
    pass


@dataclass(frozen=True)
class Transaction:
    plan_id: str
    plan: dict[str, Any]


def _interface():
    try:
        import dbus
    except ImportError as exc:
        raise BackendError("The Linxira system D-Bus client is unavailable") from exc
    bus = dbus.SystemBus()
    proxy = bus.get_object(BUS_NAME, OBJECT_PATH)
    return dbus.Interface(proxy, INTERFACE)


def _document(value: str, description: str) -> dict[str, Any]:
    try:
        document = json.loads(value)
    except json.JSONDecodeError as exc:
        raise BackendError(f"System backend returned invalid {description}") from exc
    if not isinstance(document, dict):
        raise BackendError(f"System backend returned invalid {description}")
    return document


def create_diagnosis_plan(interface=None) -> Transaction:
    client = _interface() if interface is None else interface
    try:
        plan_id, plan_json = client.CreateSystemPlan(HARDWARE_DIAGNOSIS, "{}", timeout=120)
    except Exception as exc:
        raise BackendError(str(exc)) from exc
    plan = _document(str(plan_json), "hardware diagnosis plan")
    if plan.get("id") != str(plan_id) or plan.get("operationId") != HARDWARE_DIAGNOSIS:
        raise BackendError("System backend returned a mismatched hardware plan")
    if plan.get("risk") != "read-only" or not isinstance(plan.get("digest"), str):
        raise BackendError("System backend returned an unsafe hardware plan")
    return Transaction(str(plan_id), plan)


def run_diagnosis(transaction: Transaction, interface=None) -> dict[str, Any]:
    client = _interface() if interface is None else interface
    try:
        receipt_id, receipt_json = client.ConfirmAndApplySystemPlan(
            transaction.plan_id, transaction.plan["digest"], timeout=120
        )
    except Exception as exc:
        raise BackendError(str(exc)) from exc
    receipt = _document(str(receipt_json), "hardware diagnosis receipt")
    if receipt.get("id") != str(receipt_id) or receipt.get("planId") != transaction.plan_id:
        raise BackendError("System backend returned a mismatched hardware receipt")
    if (
        receipt.get("planDigest") != transaction.plan.get("digest")
        or receipt.get("operationId") != HARDWARE_DIAGNOSIS
        or receipt.get("status") != "succeeded"
        or receipt.get("changed") is not False
    ):
        raise BackendError("Hardware diagnosis did not complete safely")
    return receipt
