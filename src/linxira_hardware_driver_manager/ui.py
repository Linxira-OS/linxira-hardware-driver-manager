from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .policy import POLICY_BY_ID
from .reporting import build_plan, save_plan_atomic


class MainWindow(QMainWindow):
    def __init__(self, report: dict):
        super().__init__()
        self.report = report
        self.plan: dict | None = None
        self.setWindowTitle("Linxira Hardware and Driver Manager")
        self.resize(1050, 720)
        self._build()

    def _text_view(self, value: object) -> QPlainTextEdit:
        view = QPlainTextEdit(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True))
        view.setReadOnly(True)
        font = QFont("monospace")
        font.setStyleHint(QFont.StyleHint.Monospace)
        view.setFont(font)
        return view

    def _build(self) -> None:
        tabs = QTabWidget()
        profiles = ", ".join(self.report["detector"]["profileIds"]) or "No hardware profiles detected"
        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        heading = QLabel("Detected hardware facts")
        heading.setStyleSheet("font-size: 18px; font-weight: 600")
        overview_layout.addWidget(heading)
        facts = QLabel(profiles)
        facts.setWordWrap(True)
        overview_layout.addWidget(facts)
        overview_layout.addWidget(QLabel(f"Detector: {self.report['detector']['metadata']['name']} {self.report['detector']['metadata']['version']}"))
        overview_layout.addStretch()
        tabs.addTab(overview, "Overview")

        drivers = QWidget()
        driver_layout = QVBoxLayout(drivers)
        driver_layout.addWidget(QLabel("Recommended fixed policy"))
        self.selector = QComboBox()
        for item in self.report["recommendations"]:
            self.selector.addItem(item["title"], item["policyId"])
        self.selector.currentIndexChanged.connect(self._refresh_plan)
        driver_layout.addWidget(self.selector)
        self.plan_view = self._text_view({})
        self.plan_view.setAccessibleName("Complete read-only driver plan")
        driver_layout.addWidget(self.plan_view, 1)
        controls = QHBoxLayout()
        self.confirm = QCheckBox("I reviewed this exact plan")
        self.confirm.stateChanged.connect(self._confirmation_changed)
        controls.addWidget(self.confirm)
        controls.addStretch()
        self.save_button = QPushButton("Save plan")
        self.save_button.clicked.connect(self._save)
        controls.addWidget(self.save_button)
        self.apply_button = QPushButton("Apply")
        self.apply_button.setEnabled(False)
        self.apply_button.setToolTip("Backend not ready; this MVP cannot apply changes")
        controls.addWidget(self.apply_button)
        driver_layout.addLayout(controls)
        self.backend_status = QLabel("Apply unavailable: backend-not-ready")
        driver_layout.addWidget(self.backend_status)
        tabs.addTab(drivers, "Drivers")

        tree = QTreeWidget()
        tree.setHeaderLabels(["Kernel", "Installed", "Headers", "DKMS"])
        for kernel in self.report["installedState"]["kernels"]:
            header = f"{kernel['package']}-headers"
            dkms_ok = any(item["kernelRelease"] == kernel["release"] and item["status"] == "installed" for item in self.report["installedState"]["dkms"])
            QTreeWidgetItem(tree, [kernel["package"], kernel["release"], "yes" if self.report["installedState"]["packages"][header]["installed"] else "missing", "installed" if dkms_ok else "not validated"])
        tabs.addTab(tree, "Kernel compatibility")
        tabs.addTab(self._text_view(self.report), "Activity / report")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(tabs)
        self.setCentralWidget(container)
        self._refresh_plan()

    def _refresh_plan(self) -> None:
        policy_id = self.selector.currentData()
        self.plan = build_plan(self.report, policy_id) if policy_id else None
        self.plan_view.setPlainText(json.dumps(self.plan or {}, ensure_ascii=True, indent=2, sort_keys=True))
        self.confirm.setChecked(False)
        self.save_button.setEnabled(False)

    def _confirmation_changed(self, state: int) -> None:
        self.save_button.setEnabled(state == Qt.CheckState.Checked.value and self.plan is not None)

    def _save(self) -> None:
        if self.plan is not None and self.confirm.isChecked():
            path = save_plan_atomic(self.plan)
            self.backend_status.setText(f"Plan saved: {path}. Apply unavailable: backend-not-ready")
