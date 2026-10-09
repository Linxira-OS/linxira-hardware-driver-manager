# linxira-hardware-driver-manager · Agent 开发规范

> **档位**:A 档 · 系统源仓(带 `VERSION` + `.github/workflows/release.yml`)。
> **本仓职责**:硬件与驱动**报告**及**固定策略规划** UI,并可通过共享 Linxira 系统事务服务发起 root 只读诊断。
> 通用条款见工作区总纲 `f:\Linxira-OS\AGENTS.md`;发布/测试口径见 `linxira-os/docs/RELEASE_STANDARD.md`。本文件只写本仓特有约定。

## 职责与边界

- **负责**:消费 `/usr/bin/linxira-hwd-detector`(无参)读取硬件事实;生成固定策略计划;经共享系统事务服务发起 root 只读诊断。
- **硬件事实与包策略分离**:detector JSON 严格解析,已安装状态**只**来自固定内核/包/DKMS/initramfs/module/reboot 证据。
- **提权与执行边界**:Driver Apply 仅在**固定的 Hyper-V / QEMU / VMware 客体策略**下可用;apply 需要 root 所属计划、已校验的 Timeshift Btrfs 变更前快照、未变的仓库与硬件证据、固定包执行、平台专属服务校验与不可变回执。**VirtualBox 在双内核模块 provider 修复前保持不可用。** root 诊断走固定操作 ID、空参数、可审阅的短生命周期计划与不可变回执,**不做任何包/服务/系统文件变更**。
- **不负责**:事务后端本体(归 `linxira-components`);硬件检测本体(归 `linxira-hwd-detector`)。

## 目录布局

```
src/linxira_hardware_driver_manager/  app.py / ui.py / detector.py / policy.py
                                      reporting.py / backend.py / state.py / about.py
data/                                 org.linxira.HardwareDriverManager.desktop / .metainfo.xml
tests/                                test_detector / test_policy_and_plan / test_backend
                                      test_state_cli_ui / test_about_metadata
```

## 本地校验

```sh
python -m pip install -e .
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
python -m compileall -q src tests
```

CI(`.github/workflows/ci.yml`,Python 3.11)跑 `pip install .`、offscreen 单测、compileall 与 wheel 构建。

## CLI 事实

```console
linxira-hardware-driver-manager --report-json
linxira-hardware-driver-manager --plan org.linxira.driver.intel-mesa.v1 --json
```

`--plan` **只接受 `--help` 展示的策略 ID**;生成的计划记录确切策略、硬编码包集、detector 摘要、许可、内核/header 与 DKMS 谓词、影响、警告、阻断项、适用性与完整性摘要。

## 版本与发布

- 版本唯一来源是根目录 `VERSION`(当前 0.4.0);`pyproject.toml` version 必须同步。
- CLI 入口:`linxira-hardware-driver-manager = linxira_hardware_driver_manager.app:main`(依赖 `PySide6>=6.7`,Python ≥ 3.11)。
- 提交 `VERSION` 变更即触发 `.github/workflows/release.yml` 走全自动发布链。**禁止手工 bump**。

## 禁区

- 子进程一律**固定参数列表 + `shell=False` + 超时**;不得接受任意 path / package / command 输入。
- 只支持 `linux` 与 `linux-lts` 及其匹配 headers;NVIDIA open/专有是需显式评审的**替代方案**,不得宣称设备 ID 支持;专有 DKMS 对比当前被阻断。
- 计划原子写入,权限私有:`$XDG_STATE_HOME/linxira/hardware-driver-manager/plans`。
- 不得绕过 `linxira-components` 系统事务服务直接提权或调包管理器;提权只走 `linxira-components` + polkit。