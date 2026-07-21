from __future__ import annotations

import argparse
import json
import os
import sys

from .policy import POLICY_IDS
from .reporting import build_report, build_plan, save_plan_atomic


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="linxira-hardware-driver-manager")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--report-json", action="store_true", help="Print the read-only report as JSON")
    mode.add_argument("--plan", choices=POLICY_IDS, metavar="POLICY_ID", help="Create a fixed-policy plan")
    parser.add_argument("--json", action="store_true", help="Print plan JSON (valid only with --plan)")
    parsed = parser.parse_args(argv)
    if parsed.json and not parsed.plan:
        parser.error("--json requires --plan")
    return parsed


def main(argv: list[str] | None = None) -> int:
    args = arguments(argv)
    try:
        report = build_report()
    except RuntimeError as exc:
        print(f"hardware report unavailable: {exc}", file=sys.stderr)
        return 2
    if args.report_json:
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 0
    if args.plan:
        plan = build_plan(report, args.plan)
        path = save_plan_atomic(plan)
        if args.json:
            print(json.dumps(plan, ensure_ascii=True, indent=2, sort_keys=True))
        else:
            print(path)
        return 0 if plan["applicable"] else 3

    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from PySide6.QtWidgets import QApplication
    from .ui import MainWindow

    application = QApplication(sys.argv[:1])
    application.setApplicationName("Linxira Hardware and Driver Manager")
    application.setOrganizationName("Linxira OS")
    window = MainWindow(report)
    window.show()
    return application.exec()
