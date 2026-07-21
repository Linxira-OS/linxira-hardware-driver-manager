# Linxira Hardware and Driver Manager

Phase 1 read-only hardware and driver reporting and fixed-policy planning UI for
Linxira OS. It consumes `/usr/bin/linxira-chwd-detector` with no arguments and
keeps hardware facts separate from package policy.

## Safety boundary

- Detector JSON uses strict duplicate-key parsing and exact schema, name, and version validation.
- Every subprocess is a fixed argument list with `shell=False` and a timeout.
- Installed state comes only from fixed kernel, package, DKMS, initramfs, module, and reboot evidence.
- Only `linux` and `linux-lts`, with their matching headers, are supported.
- Policies and package names are declarative constants; no path, package, or command input is accepted.
- NVIDIA open and proprietary plans are alternatives requiring explicit review. No device-ID support claim is made. The proprietary DKMS comparison is blocked because the reviewed official Arch cohort currently has no dual-kernel package for it.
- Plans are written atomically with private permissions below `$XDG_STATE_HOME/linxira/hardware-driver-manager/plans`.
- Apply is deliberately unavailable. The manager performs no package, service, privilege, or system-file changes.

## CLI

```console
linxira-hardware-driver-manager --report-json
linxira-hardware-driver-manager --plan org.linxira.driver.intel-mesa.v1 --json
```

`--plan` accepts only the policy IDs shown by `--help`. A generated plan records
the exact policy, hardcoded package set, detector digest, licensing, kernel/header
and DKMS predicates, effects, warnings, blockers, applicability, and an integrity digest.

## Development

```console
python -m pip install -e .
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
python -m compileall -q src tests
```
