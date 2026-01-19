import os
import sys
import unittest


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from newodometer import NewFilamentOdometer


class TestOdometer(unittest.TestCase):

	def test_checksum_delimited_values_are_parsed(self):
		odometer = NewFilamentOdometer()
		odometer.processGCodeLine("N1 M82*0")
		odometer.processGCodeLine("N2 G1 X0.0 E10.0*0")
		odometer.processGCodeLine("N3 G1 X1.0 E12.5*0")
		odometer.processGCodeLine("N4 G1 E11.0*0")
		self.assertAlmostEqual(odometer.getExtrusionAmount()[0], 12.5)

	def test_m221_flow_factor_scales_extrusion(self):
		odometer = NewFilamentOdometer()
		odometer.processGCodeLine("M82")
		odometer.processGCodeLine("M221 S110")
		odometer.processGCodeLine("G1 E10")
		odometer.processGCodeLine("G1 E20")
		self.assertAlmostEqual(odometer.getExtrusionAmount()[0], 22.0)

	def test_m221_can_be_set_per_tool(self):
		odometer = NewFilamentOdometer()
		odometer.processGCodeLine("M83")
		odometer.processGCodeLine("T1")
		odometer.processGCodeLine("M221 T1 S120")
		odometer.processGCodeLine("G1 E10")
		self.assertAlmostEqual(odometer.getExtrusionAmount()[1], 12.0)

if __name__ == '__main__':
	unittest.main()
