from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from linxira_hardware_driver_manager.policy import POLICY_BY_ID, POLICY_IDS, recommendations
from linxira_hardware_driver_manager.reporting import build_plan, save_plan_atomic
from linxira_hardware_driver_manager.state import collect_system_state

from helpers import FixedRunner, report_for, write_state_files


INTEL = "org.linxira.driver.intel-mesa.v1"
AMD = "org.linxira.driver.amd-mesa.v1"
NVIDIA_OPEN = "org.linxira.driver.nvidia-open-dkms.v1"
NVIDIA_PROPRIETARY = "org.linxira.driver.nvidia-proprietary-dkms.v1"


class PolicyTests(unittest.TestCase):
    def test_intel_amd_nvidia_hybrid_and_vm_recommendations(self) -> None:
        cases = {
            ("graphics.intel",): {INTEL},
            ("graphics.amd",): {AMD},
            ("graphics.nvidia",): {NVIDIA_OPEN, NVIDIA_PROPRIETARY},
            ("graphics.hybrid", "graphics.intel", "graphics.nvidia"): {INTEL, NVIDIA_OPEN, NVIDIA_PROPRIETARY},
            ("vm.qemu",): {"org.linxira.driver.vm-qemu-guest.v1"},
            ("vm.hyperv",): {"org.linxira.driver.vm-hyperv-guest.v1"},
        }
        for facts, expected in cases.items():
            with self.subTest(facts=facts):
                self.assertEqual({item.id for item in recommendations(list(facts))}, expected)

    def test_nvidia_is_always_review_choice_without_device_claim(self) -> None:
        for policy_id in (NVIDIA_OPEN, NVIDIA_PROPRIETARY):
            policy = POLICY_BY_ID[policy_id]
            self.assertTrue(policy.requires_review)
            self.assertEqual(policy.fact_id, "graphics.nvidia")
        self.assertNotEqual(POLICY_BY_ID[NVIDIA_OPEN].driver_model, POLICY_BY_ID[NVIDIA_PROPRIETARY].driver_model)
        self.assertTrue(POLICY_BY_ID[NVIDIA_OPEN].available)
        self.assertFalse(POLICY_BY_ID[NVIDIA_PROPRIETARY].available)


class PlanTests(unittest.TestCase):
    def _state(self, root: Path, *, headers: bool = True, dkms_status: str = "installed") -> dict:
        kernels = (("linux", "6.12.1-arch1-1"), ("linux-lts", "6.6.9-arch1-1"))
        paths = write_state_files(root, kernels)
        installed = {"linux", "linux-lts", "nvidia-open-dkms", "nvidia-utils", "lib32-nvidia-utils"}
        if headers:
            installed.update({"linux-headers", "linux-lts-headers"})
        dkms = (
            f"nvidia/570.0, 6.12.1-arch1-1, x86_64: {dkms_status}\n"
            f"nvidia/570.0, 6.6.9-arch1-1, x86_64: {dkms_status}\n"
        )
        return collect_system_state(FixedRunner(installed, dkms), **paths)

    def test_linux_and_linux_lts_headers_and_dkms_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(Path(directory))
            plan = build_plan(report_for(["graphics.nvidia"], state), NVIDIA_OPEN)
        self.assertTrue(plan["applicable"])
        self.assertEqual([item["kernelPackage"] for item in plan["validation"]["dkms"]], ["linux", "linux-lts"])
        self.assertTrue(all(item["headerPresent"] for item in plan["validation"]["kernelHeaders"]))
        self.assertTrue(all(item["satisfied"] for item in plan["validation"]["dkms"]))
        self.assertTrue(plan["effects"]["initramfsRegenerationExpected"])

    def test_missing_header_is_visible_and_in_fixed_packages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(Path(directory), headers=False)
            plan = build_plan(report_for(["graphics.nvidia"], state), NVIDIA_OPEN)
        self.assertFalse(all(item["headerPresent"] for item in plan["validation"]["kernelHeaders"]))
        self.assertIn("linux-headers", plan["policy"]["packages"])
        self.assertTrue(any("headers" in warning.lower() for warning in plan["warnings"]))

    def test_dkms_failure_is_not_reported_as_satisfied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(Path(directory), dkms_status="added")
            plan = build_plan(report_for(["graphics.nvidia"], state), NVIDIA_OPEN)
        self.assertFalse(any(item["satisfied"] for item in plan["validation"]["dkms"]))
        self.assertFalse(plan["applicable"])
        self.assertTrue(any("DKMS" in item for item in plan["blockers"]))

    def test_new_dkms_install_can_be_planned_before_build_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(Path(directory), dkms_status="added")
            state["packages"]["nvidia-open-dkms"] = {"installed": False, "version": None}
            plan = build_plan(report_for(["graphics.nvidia"], state), NVIDIA_OPEN)
        self.assertTrue(plan["applicable"])

    def test_graphics_plan_discloses_multilib_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(Path(directory))
            plan = build_plan(report_for(["graphics.nvidia"], state), NVIDIA_OPEN)
        self.assertEqual(plan["effects"]["repositoryChanges"], ["arch-multilib-required"])

    def test_hyperv_plan_discloses_fixed_service_enablement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(Path(directory))
            plan = build_plan(
                report_for(["vm.hyperv"], state), "org.linxira.driver.vm-hyperv-guest.v1"
            )
        self.assertEqual(plan["effects"]["serviceChanges"], [
            "enable:hv_kvp_daemon.service", "enable:hv_vss_daemon.service",
        ])

    def test_unavailable_proprietary_policy_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(Path(directory))
            plan = build_plan(report_for(["graphics.nvidia"], state), NVIDIA_PROPRIETARY)
        self.assertFalse(plan["applicable"])
        self.assertTrue(any("official Arch cohort" in item for item in plan["blockers"]))

    def test_absent_fact_or_kernel_blocks_applicability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = write_state_files(Path(directory), (("linux", "6.12.1-arch1-1"),))
            state = collect_system_state(FixedRunner({"linux", "linux-headers", "linux-lts-headers"}), **paths)
            plan = build_plan(report_for(["graphics.intel"], state), NVIDIA_OPEN)
        self.assertFalse(plan["applicable"])
        self.assertTrue(any("fact" in item.lower() for item in plan["blockers"]))
        self.assertTrue(any("linux-lts" in item for item in plan["blockers"]))

    def test_digest_and_atomic_private_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = self._state(root)
            plan = build_plan(report_for(["graphics.nvidia"], state), NVIDIA_OPEN)
            digest = plan.pop("planSha256")
            canonical = json.dumps(plan, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
            self.assertEqual(digest, hashlib.sha256(canonical).hexdigest())
            plan["planSha256"] = digest
            output = save_plan_atomic(plan, root / "state" / "plans")
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), plan)
            self.assertEqual(output.name, digest + ".json")
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(output.parent.stat().st_mode), 0o700)
            self.assertFalse(any(path.name.endswith(".tmp") for path in output.parent.iterdir()))

    @unittest.skipIf(os.name == "nt", "Windows symlink creation requires elevated privileges")
    def test_plan_directory_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            real.mkdir()
            link = root / "plans"
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                save_plan_atomic({"planSha256": "0" * 64}, link)

    def test_policy_ids_and_packages_are_fixed(self) -> None:
        self.assertEqual(len(POLICY_IDS), len(set(POLICY_IDS)))
        for policy in POLICY_BY_ID.values():
            self.assertTrue(policy.id.endswith(".v1"))
            self.assertTrue(policy.packages)
            self.assertTrue(all("/" not in package and " " not in package for package in policy.packages))


if __name__ == "__main__":
    unittest.main()
