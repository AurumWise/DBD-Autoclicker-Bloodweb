import unittest

from app.safety.center_anchor import (
    CENTER_CONFIRMED,
    CENTER_NOT_CONFIRMED,
    CENTER_RECHECKING,
    CENTER_UNCONFIGURED,
    CenterConfirmationMachine,
)


class CenterConfirmationMachineTest(unittest.TestCase):
    def test_unconfigured_blocks_clicks(self):
        machine = CenterConfirmationMachine(configured=False)
        self.assertEqual(machine.state, CENTER_UNCONFIGURED)
        self.assertFalse(machine.clicks_allowed)
        self.assertEqual(machine.regular_result(True), "none")
        self.assertFalse(machine.clicks_allowed)

    def test_two_successes_confirm_center(self):
        machine = CenterConfirmationMachine(configured=True)
        self.assertEqual(machine.regular_result(True), "none")
        self.assertEqual(machine.state, CENTER_NOT_CONFIRMED)
        self.assertFalse(machine.clicks_allowed)
        self.assertEqual(machine.regular_result(True), "confirmed")
        self.assertEqual(machine.state, CENTER_CONFIRMED)
        self.assertTrue(machine.clicks_allowed)

    def test_first_miss_after_confirmed_blocks_and_rechecks(self):
        machine = CenterConfirmationMachine(configured=True)
        machine.regular_result(True)
        machine.regular_result(True)
        self.assertEqual(machine.regular_result(False), "recheck")
        self.assertEqual(machine.state, CENTER_RECHECKING)
        self.assertFalse(machine.clicks_allowed)

    def test_recheck_success_restores_confirmed(self):
        machine = CenterConfirmationMachine(configured=True)
        machine.regular_result(True)
        machine.regular_result(True)
        machine.regular_result(False)
        self.assertEqual(machine.recheck_results([False, True]), "confirmed")
        self.assertEqual(machine.state, CENTER_CONFIRMED)
        self.assertTrue(machine.clicks_allowed)

    def test_recheck_failure_loses_center_and_requires_manual_start(self):
        machine = CenterConfirmationMachine(configured=True)
        machine.regular_result(True)
        machine.regular_result(True)
        machine.regular_result(False)
        self.assertEqual(machine.recheck_results([False, False]), "lost")
        self.assertEqual(machine.state, CENTER_NOT_CONFIRMED)
        self.assertFalse(machine.clicks_allowed)
        self.assertTrue(machine.requires_manual_start)


if __name__ == "__main__":
    unittest.main()
