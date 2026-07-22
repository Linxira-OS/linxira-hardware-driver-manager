from __future__ import annotations

import json
import unittest
from unittest import mock

from linxira_hardware_driver_manager.backend import (
    BackendError,
    HARDWARE_DIAGNOSIS,
    create_diagnosis_plan,
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
