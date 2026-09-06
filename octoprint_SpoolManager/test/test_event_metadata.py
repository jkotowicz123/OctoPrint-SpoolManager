"""Exercise the production metadata reader without loading OctoPrint plugins."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import Mock
from datetime import datetime

source = Path(__file__).parents[1].joinpath('__init__.py').read_text()
tree = ast.parse(source)
methods = [node for cls in tree.body if isinstance(cls, ast.ClassDef)
           for node in cls.body if isinstance(node, ast.FunctionDef)
           and node.name in ('_readingFilamentMetaData', '_getCurrentJobFile', 'commitOdometerData', '_on_printJobFinished')]
namespace = {
    'datetime': datetime,
    'StringUtils': SimpleNamespace(isEmpty=lambda x: x is None),
    'EventBusKeys': SimpleNamespace(EVENT_BUS_SPOOL_WEIGHT_UPDATED_AFTER_PRINT='usage'),
    'remaining_metadata_length': lambda total, committed: max(0, total-committed),
}
exec(compile(ast.Module(body=methods, type_ignores=[]), '<production-methods>', 'exec'), namespace)

class EventMetadataTests(TestCase):
    def setUp(self):
        self.plugin = SimpleNamespace()
        for name, method in namespace.items():
            if name in {node.name for node in methods}:
                setattr(self.plugin, name, method.__get__(self.plugin))
        self.plugin._printer = SimpleNamespace(get_current_data=lambda: {
            'job': {'file': {'origin':'local', 'path':'next.gcode'}}})
        self.plugin._file_manager = SimpleNamespace(get_metadata=Mock(side_effect=lambda origin, path: {
            'load.gcode': {},
            'model.gcode': {'analysis':{'filament':{'tool0':{'length':909}}}},
            'next.gcode': {'analysis':{'filament':{'tool0':{'length':50000}}}},
        }[path]))

    def prepare_accounting(self, odometer, committed=0):
        p = self.plugin
        spool = SimpleNamespace(usedLength=0, usedWeight=0, diameter=1.75, density=1.24,
            displayName='test', databaseId=1, material='PLA', colorName='blue', remainingWeight=100)
        p.loadSelectedSpools = lambda: [spool]
        p._getSpoolAccountingTargets = lambda _: [(0,0,spool)]
        p._committedPrintFilamentLengths = {0:committed}
        p._mmuRoutingSession = SimpleNamespace(active=False)
        p.myFilamentOdometer = SimpleNamespace(getExtrusionAmount=lambda:[odometer],reset_extruded_length=Mock())
        p._logger = Mock()
        p._databaseManager = SimpleNamespace(saveSpool=Mock())
        p._calculateWeight = lambda mm, diameter, density: mm
        p._sendPayload2EventBus = Mock()
        p._sendDataToClient = Mock()
        p._evaluateRequiredWeight = lambda *args: {}
        p.clear_temp_offsets = Mock()
        return spool

    def test_finished_handler_accounts_event_file_not_next_selection(self):
        spool = self.prepare_accounting(920)
        self.plugin._on_printJobFinished('success', {'origin':'local','path':'model.gcode'})
        self.assertEqual(spool.usedLength, 909)
        self.plugin._sendPayload2EventBus.assert_called_once()

    def test_finished_load_script_does_not_charge_next_model(self):
        spool = self.prepare_accounting(0)
        self.plugin._on_printJobFinished('success', {'origin':'local','path':'load.gcode'})
        self.assertEqual(spool.usedLength, 0)

    def test_zero_metadata_remainder_does_not_fall_back_to_odometer(self):
        spool = self.prepare_accounting(20, committed=909)
        self.plugin._on_printJobFinished('success', {'origin':'local','path':'model.gcode'})
        self.assertEqual(spool.usedLength, 0)

    def test_load_done_does_not_charge_the_next_models_metadata(self):
        self.assertFalse(self.plugin._readingFilamentMetaData({'origin':'local','path':'load.gcode'}))
        self.assertEqual(self.plugin.metaDataFilamentLengths, [])
        self.plugin._printer.get_current_data = Mock(side_effect=AssertionError('snapshot must not be read'))
        self.assertFalse(self.plugin._readingFilamentMetaData({'origin':'local','path':'load.gcode'}))

    def test_model_done_uses_completed_file_even_after_next_file_selected(self):
        self.assertTrue(self.plugin._readingFilamentMetaData({'origin':'local','path':'model.gcode'}))
        self.assertEqual(self.plugin.metaDataFilamentLengths, [909])

    def test_selection_validation_still_reads_current_file(self):
        self.assertTrue(self.plugin._readingFilamentMetaData())
        self.assertEqual(self.plugin.metaDataFilamentLengths, [50000])

if __name__ == '__main__':
    main()
