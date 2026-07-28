from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from linxira_hardware_driver_manager.app import arguments
from linxira_hardware_driver_manager.policy import ALL_PACKAGES
from linxira_hardware_driver_manager.state import DKMS, PACMAN, UNAME, collect_system_state

from helpers import FixedRunner, report_for, write_state_files


class StateAndCliTests(unittest.TestCase):
    def test_state_uses_only_fixed_read_only_argv_and_shell_false(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = write_state_files(Path(directory))
            runner = FixedRunner({"linux", "linux-headers"})
            collect_system_state(runner, **paths)
        argv = [call[0] for call in runner.calls]
        self.assertIn([UNAME, "-r"], argv)
        self.assertIn([DKMS, "status"], argv)
        self.assertEqual({tuple(item) for item in argv if item[0] == PACMAN}, {(PACMAN, "-Q", package) for package in ALL_PACKAGES})
        for command, kwargs in runner.calls:
            self.assertIs(kwargs["shell"], False)
            self.assertGreater(kwargs["timeout"], 0)
            self.assertNotIn(command[1] if len(command) > 1 else "", {"-S", "-R", "-U", "install", "remove", "enable", "start"})

    def test_cli_has_choices_and_no_path_package_or_command_flags(self) -> None:
        parsed = arguments(["--plan", "org.linxira.driver.intel-mesa.v1", "--json"])
        self.assertEqual(parsed.plan, "org.linxira.driver.intel-mesa.v1")
        with self.assertRaises(SystemExit):
            arguments(["--plan", "arbitrary"])
        with self.assertRaises(SystemExit):
            arguments(["--path", "/tmp/input"])


try:
    from PySide6.QtWidgets import QApplication
    from linxira_hardware_driver_manager.ui import MainWindow
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 is unavailable")
class UiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_offscreen_window_has_visible_plan_and_disabled_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = write_state_files(Path(directory), (("linux", "6.12.1-arch1-1"), ("linux-lts", "6.6.9-arch1-1")))
            state = collect_system_state(FixedRunner({"linux", "linux-lts", "linux-headers", "linux-lts-headers"}), **paths)
        report = report_for(["graphics.nvidia"], state)
        report["recommendations"] = [
            {"policyId": "org.linxira.driver.nvidia-open-dkms.v1", "title": "NVIDIA open kernel modules (review required)"},
            {"policyId": "org.linxira.driver.nvidia-proprietary-dkms.v1", "title": "NVIDIA proprietary DKMS (review required)"},
        ]
        window = MainWindow(report)
        self.assertIn("org.linxira.driver.nvidia-open-dkms.v1", window.plan_view.toPlainText())
        self.assertFalse(window.apply_button.isEnabled())
        self.assertTrue(window.diagnosis_button.isEnabled())
        self.assertIn("No root-owned diagnosis", window.diagnosis_status.text())
        self.assertFalse(window.save_button.isEnabled())
        window.confirm.setChecked(True)
        self.assertTrue(window.save_button.isEnabled())
        self.assertFalse(window.apply_button.isEnabled())
        self.assertIn("backend-not-ready", window.backend_status.text())
        window.close()

    def test_close_is_deferred_while_root_diagnosis_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = write_state_files(Path(directory))
            state = collect_system_state(FixedRunner({
                "linux", "linux-headers", "linux-lts", "linux-lts-headers",
            }), **paths)
        window = MainWindow(report_for(["graphics.intel"], state))
        window.diagnosis_plan_worker = type("Worker", (), {"isRunning": lambda self: True})()
        event = type("Event", (), {"ignore": Mock()})()
        with patch("linxira_hardware_driver_manager.ui.QMessageBox.information"):
            window.closeEvent(event)
        event.ignore.assert_called_once()
        window.diagnosis_plan_worker = None
        window.close()

    def test_only_applicable_hyperv_policy_enables_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = write_state_files(
                Path(directory), (("linux", "6.12.1-arch1-1"), ("linux-lts", "6.6.9-arch1-1")),
            )
            state = collect_system_state(FixedRunner({
                "linux", "linux-headers", "linux-lts", "linux-lts-headers",
            }), **paths)
        report = report_for(["vm.hyperv"], state)
        report["recommendations"] = [{
            "policyId": "org.linxira.driver.vm-hyperv-guest.v1", "title": "Hyper-V guest tools",
        }]
        window = MainWindow(report)
        self.assertFalse(window.apply_button.isEnabled())
        window.confirm.setChecked(True)
        self.assertTrue(window.apply_button.isEnabled())
        self.assertIn("Timeshift snapshot", window.backend_status.text())
        window.close()

    def test_successful_driver_apply_rebuilds_installed_state_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = write_state_files(Path(directory))
            state = collect_system_state(FixedRunner({"linux", "linux-headers"}), **paths)
        report = report_for(["vm.hyperv"], state)
        report["recommendations"] = [{
            "policyId": "org.linxira.driver.vm-hyperv-guest.v1", "title": "Hyper-V guest tools",
        }]
        refreshed = dict(report)
        refreshed["generatedAt"] = "refreshed"
        window = MainWindow(report)
        with patch("linxira_hardware_driver_manager.ui.build_report", return_value=refreshed) as rebuild, \
             patch("linxira_hardware_driver_manager.ui.QMessageBox.information"):
            window._driver_complete({"id": "receipt", "status": "succeeded"})
        rebuild.assert_called_once_with()
        self.assertEqual(window.report["generatedAt"], "refreshed")
        self.assertIn("refreshed", window.report_view.toPlainText())
        window.close()

    def test_qemu_and_vmware_enable_apply_but_virtualbox_stays_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = write_state_files(
                Path(directory), (("linux", "6.12.1-arch1-1"), ("linux-lts", "6.6.9-arch1-1")),
            )
            state = collect_system_state(FixedRunner({
                "linux", "linux-headers", "linux-lts", "linux-lts-headers",
            }), **paths)
        cases = (
            ("vm.qemu", "org.linxira.driver.vm-qemu-guest.v1", True),
            ("vm.vmware", "org.linxira.driver.vm-vmware-guest.v1", True),
            ("vm.virtualbox", "org.linxira.driver.vm-virtualbox-guest.v1", False),
        )
        for fact, policy_id, expected in cases:
            report = report_for([fact], state)
            report["recommendations"] = [{"policyId": policy_id, "title": fact}]
            window = MainWindow(report)
            window.confirm.setChecked(True)
            self.assertEqual(window.apply_button.isEnabled(), expected)
            window.close()


if __name__ == "__main__":
    unittest.main()
