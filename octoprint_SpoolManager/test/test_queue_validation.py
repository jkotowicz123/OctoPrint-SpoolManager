"""Verify that autonomous queues cannot bypass filament safety settings."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main


source = Path(__file__).parents[1].joinpath("api", "SpoolManagerAPI.py").read_text()
tree = ast.parse(source)
methods = []
for cls in tree.body:
    if not isinstance(cls, ast.ClassDef):
        continue
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name in {
            "allowed_to_print",
            "allowed_to_print_for_queue",
        }:
            node.decorator_list = []
            methods.append(node)

namespace = {
    "flask": SimpleNamespace(jsonify=lambda value: value),
    "SettingsKeys": SimpleNamespace(
        SETTINGS_KEY_WARN_IF_SPOOL_NOT_SELECTED="warn-spool",
        SETTINGS_KEY_WARN_IF_FILAMENT_NOT_ENOUGH="warn-filament",
        SETTINGS_KEY_REMINDER_SELECTING_SPOOL="reminder",
        SETTINGS_KEY_TOOL_OFFSET_ENABLED="tool-offset",
        SETTINGS_KEY_BED_OFFSET_ENABLED="bed-offset",
        SETTINGS_KEY_ENCLOSURE_OFFSET_ENABLED="enclosure-offset",
    ),
}
exec(compile(ast.Module(body=methods, type_ignores=[]), "<queue-validation>", "exec"), namespace)


class QueueValidationTests(TestCase):
    def setUp(self):
        spool = SimpleNamespace(
            displayName="PLA blue",
            material="PLA",
            remainingWeight=40,
            offsetTemperature=0,
            offsetBedTemperature=0,
            offsetEnclosureTemperature=0,
        )
        self.plugin = SimpleNamespace(
            _settings=SimpleNamespace(get_boolean=lambda _: False),
            loadSelectedSpools=lambda: [spool],
            _readingFilamentMetaData=lambda: True,
            metaDataFilamentLengths=[100],
            _printer_profile_manager=SimpleNamespace(
                get_current_or_default=lambda: {"extruder": {"count": 1}}
            ),
            checkRemainingFilament=lambda _: {
                "metaDataMissing": False,
                "attributesMissing": False,
                "detailedSpoolResult": [{
                    "spoolSelected": True,
                    "requiredLength": 100,
                    "notEnough": True,
                }],
            },
        )
        for name in ("allowed_to_print", "allowed_to_print_for_queue"):
            setattr(self.plugin, name, namespace[name].__get__(self.plugin))

    def test_interactive_endpoint_still_respects_disabled_warning(self):
        response = self.plugin.allowed_to_print()
        self.assertEqual(response["result"]["filamentNotEnough"], [])

    def test_queue_validation_always_reports_insufficient_filament(self):
        response = self.plugin.allowed_to_print_for_queue()
        self.assertEqual(len(response["result"]["filamentNotEnough"]), 1)


if __name__ == "__main__":
    main()
