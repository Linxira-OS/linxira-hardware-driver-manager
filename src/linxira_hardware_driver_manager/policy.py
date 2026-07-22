from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Policy:
    id: str
    title: str
    fact_id: str
    packages: tuple[str, ...]
    driver_model: str
    license: str
    requires_dkms: bool = False
    requires_review: bool = False
    repository_changes: tuple[str, ...] = ()
    available: bool = True
    unavailable_reason: str | None = None


POLICIES = (
    Policy("org.linxira.driver.intel-mesa.v1", "Intel Mesa", "graphics.intel", ("mesa", "vulkan-intel", "lib32-mesa", "lib32-vulkan-intel"), "open", "MIT", repository_changes=("arch-multilib-required",)),
    Policy("org.linxira.driver.amd-mesa.v1", "AMD Mesa", "graphics.amd", ("mesa", "vulkan-radeon", "lib32-mesa", "lib32-vulkan-radeon"), "open", "MIT", repository_changes=("arch-multilib-required",)),
    Policy("org.linxira.driver.nvidia-open-dkms.v1", "NVIDIA open kernel modules (review required)", "graphics.nvidia", ("nvidia-open-dkms", "nvidia-utils", "lib32-nvidia-utils", "linux-headers", "linux-lts-headers"), "open-kernel/proprietary-userspace", "GPL-2.0-only AND LicenseRef-NVIDIA", True, True, ("arch-multilib-required",)),
    Policy("org.linxira.driver.nvidia-proprietary-dkms.v1", "NVIDIA proprietary DKMS (unavailable)", "graphics.nvidia", ("nvidia-dkms", "nvidia-utils", "lib32-nvidia-utils", "linux-headers", "linux-lts-headers"), "proprietary", "LicenseRef-NVIDIA", True, True, ("arch-multilib-required",), False, "No dual-kernel proprietary NVIDIA DKMS package exists in the reviewed official Arch cohort."),
    Policy("org.linxira.driver.vm-qemu-guest.v1", "QEMU/KVM guest tools", "vm.qemu", ("qemu-guest-agent", "spice-vdagent"), "guest", "GPL-2.0-or-later"),
    Policy(
        "org.linxira.driver.vm-virtualbox-guest.v1", "VirtualBox guest tools (unavailable)",
        "vm.virtualbox", ("virtualbox-guest-utils",), "guest", "GPL-3.0-only",
        available=False,
        unavailable_reason="Dual-kernel VirtualBox guest-module providers are not fixed for linux and linux-lts.",
    ),
    Policy("org.linxira.driver.vm-vmware-guest.v1", "VMware guest tools", "vm.vmware", ("open-vm-tools",), "guest", "LGPL-2.1-only"),
    Policy("org.linxira.driver.vm-hyperv-guest.v1", "Hyper-V guest tools", "vm.hyperv", ("hyperv",), "guest", "GPL-2.0-only"),
)
POLICY_BY_ID = {policy.id: policy for policy in POLICIES}
POLICY_IDS = tuple(POLICY_BY_ID)
ALL_PACKAGES = tuple(sorted({package for policy in POLICIES for package in policy.packages} | {"linux", "linux-lts", "linux-headers", "linux-lts-headers"}))


def recommendations(profile_ids: list[str]) -> list[Policy]:
    facts = set(profile_ids)
    return [policy for policy in POLICIES if policy.fact_id in facts]
