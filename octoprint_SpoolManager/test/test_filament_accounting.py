import unittest
import importlib.util
import os

module_path = os.path.join(os.path.dirname(__file__), '..', 'filament_accounting.py')
spec = importlib.util.spec_from_file_location('filament_accounting', module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
remaining_metadata_length = module.remaining_metadata_length


class FilamentAccountingTests(unittest.TestCase):
	def test_final_spool_gets_only_metadata_remainder(self):
		self.assertAlmostEqual(remaining_metadata_length(10000, 2750), 7250)

	def test_multiple_checkpoints_are_subtracted(self):
		self.assertAlmostEqual(remaining_metadata_length(20000, 1250 + 4750), 14000)

	def test_odometer_overshoot_never_creates_negative_usage(self):
		self.assertEqual(remaining_metadata_length(1000, 1005), 0)

	def test_invalid_total_does_not_replace_odometer(self):
		self.assertIsNone(remaining_metadata_length(None, 100))


if __name__ == '__main__':
	unittest.main()
