from __future__ import annotations

import json
import unittest
from unittest import mock

from linxira_hardware_driver_manager.backend import (
    BackendError,
    HARDWARE_DIAGNOSIS,
    HYPERV_DRIVER_APPLY,
    apply_driver,
    create_diagnosis_plan,
    create_driver_plan,
    run_diagnosis,
)


class BackendTests(unittest.TestCase):
    @staticmethod
    def _transaction():
        interface = mock.Mock()
        interface.CreateSystemPlan.return_value = (
            "plan-id",
            json.dumps({
                "id": "plan-id", "operationId": HARDWARE_DIAGNOSIS,
                "risk": "read-only", "digest": "digest",
            }),
        )
        return create_diagnosis_plan(interface), interface

    def test_backend_uses_only_fixed_hardware_operation_and_empty_parameters(self):
        transaction, interface = self._transaction()
        self.assertEqual(transaction.plan_id, "plan-id")
        interface.CreateSystemPlan.assert_called_once_with(HARDWARE_DIAGNOSIS, "{}", timeout=120)

    def test_backend_binds_receipt_to_reviewed_plan(self):
        transaction, _ = self._transaction()
        interface = mock.Mock()
        interface.ConfirmAndApplySystemPlan.return_value = (
            "receipt-id",
            json.dumps({
                "id": "receipt-id", "planId": "plan-id", "planDigest": "digest",
                "operationId": HARDWARE_DIAGNOSIS, "status": "succeeded", "changed": False,
            }),
        )
        self.assertEqual(run_diagnosis(transaction, interface)["id"], "receipt-id")
        interface.ConfirmAndApplySystemPlan.assert_called_once_with("plan-id", "digest", timeout=120)

        interface.ConfirmAndApplySystemPlan.return_value = (
            "receipt-id", json.dumps({
                "id": "receipt-id", "planId": "plan-id", "planDigest": "other",
                "operationId": HARDWARE_DIAGNOSIS, "status": "succeeded", "changed": False,
            })
        )
        with self.assertRaisesRegex(BackendError, "safely"):
            run_diagnosis(transaction, interface)

    def test_hyperv_backend_requires_snapshot_plan_and_bound_receipt(self):
        interface = mock.Mock()
        interface.CreateSystemPlan.return_value = (
            "plan-id", json.dumps({
                "id": "plan-id", "operationId": HYPERV_DRIVER_APPLY,
                "risk": "system-change-reboot-possible", "digest": "digest",
                "rollback": "pre-change-timeshift-snapshot-separate-restore-authorization",
            }),
        )
        transaction = create_driver_plan(HYPERV_DRIVER_APPLY, interface)
        interface.ConfirmAndApplySystemPlan.return_value = (
            "receipt-id", json.dumps({
                "id": "receipt-id", "planId": "plan-id", "planDigest": "digest",
                "operationId": HYPERV_DRIVER_APPLY, "status": "succeeded", "changed": True,
                "rollback": "timeshift-restore-requires-separate-authorization-and-reboot",
                "snapshot": {"name": "2026-07-22_12-00-00"},
                "verifiedState": {"artifacts": [{"name": "hyperv", "version": "6.15-1"}]},
            }),
        )
        self.assertEqual(apply_driver(transaction, interface)["status"], "succeeded")
        interface.ConfirmAndApplySystemPlan.assert_called_once_with("plan-id", "digest", timeout=86400)
        with self.assertRaisesRegex(BackendError, "no executable"):
            create_driver_plan("org.linxira.driver.vm-qemu-guest.v1", interface)
