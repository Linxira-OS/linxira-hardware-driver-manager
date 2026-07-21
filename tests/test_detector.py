from __future__ import annotations

import subprocess
import unittest

from linxira_hardware_driver_manager.detector import (
    DETECTOR,
    DETECTOR_TIMEOUT_SECONDS,
    DetectorError,
    parse_detector_json,
    run_detector,
)

from helpers import detector_json


class DetectorTests(unittest.TestCase):
    def test_valid_contract(self) -> None:
        document = parse_detector_json(detector_json("cpu.intel", "graphics.intel"))
        self.assertEqual(document["profile_ids"], ["cpu.intel", "graphics.intel"])

    def test_duplicate_key_rejected(self) -> None:
        raw = detector_json("graphics.intel").replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1')
        with self.assertRaisesRegex(DetectorError, "duplicate JSON key"):
            parse_detector_json(raw)

    def test_malformed_and_contract_variants_rejected(self) -> None:
        for raw in ("{", detector_json("unknown.fact"), detector_json("graphics.intel").replace("0.1.0", "dev"), detector_json("graphics.intel").replace("linxira-chwd-detector", "other")):
            with self.subTest(raw=raw[:30]), self.assertRaises(DetectorError):
                parse_detector_json(raw)

    def test_fixed_no_argument_argv_and_shell_false(self) -> None:
        calls = []

        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, detector_json("graphics.amd"), "")

        document, digest = run_detector(runner)
        self.assertEqual(document["profile_ids"], ["graphics.amd"])
        self.assertEqual(len(digest), 64)
        self.assertEqual(calls[0][0], [DETECTOR])
        self.assertIs(calls[0][1]["shell"], False)
        self.assertEqual(calls[0][1]["timeout"], DETECTOR_TIMEOUT_SECONDS)

    def test_timeout_and_failure(self) -> None:
        def timeout(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

        with self.assertRaisesRegex(DetectorError, "timed out"):
            run_detector(timeout)
        with self.assertRaisesRegex(DetectorError, "status 7"):
            run_detector(lambda argv, **kwargs: subprocess.CompletedProcess(argv, 7, "", "failed"))


if __name__ == "__main__":
    unittest.main()
