import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "sheet_assignment.py"
SPEC = importlib.util.spec_from_file_location("sheet_assignment", str(MODULE_PATH))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TestSheetAssignment(unittest.TestCase):
	def test_refreshes_for_active_print_on_local_printer(self):
		self.assertTrue(MODULE.should_refresh_currently_printing(3, "3", True, False))

	def test_refreshes_for_paused_print_on_local_printer(self):
		self.assertTrue(MODULE.should_refresh_currently_printing("3", 3, False, True))

	def test_does_not_move_qc_history_while_idle(self):
		self.assertFalse(MODULE.should_refresh_currently_printing(3, 3, False, False))

	def test_does_not_change_another_printer(self):
		self.assertFalse(MODULE.should_refresh_currently_printing(3, 4, True, False))

	def test_rejects_missing_printer_numbers(self):
		self.assertFalse(MODULE.should_refresh_currently_printing(None, 3, True, False))


if __name__ == "__main__":
	unittest.main()
