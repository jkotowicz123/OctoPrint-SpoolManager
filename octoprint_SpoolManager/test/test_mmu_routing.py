import os
import sys
import unittest


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mmu_routing import (
    MmuRoutingSession,
    STATE_LOADED,
    STATE_UNLOADED,
    build_slot,
    continuousprint_next_path,
    missing_runtime_markers,
    parse_contract_text,
    select_slot,
    should_retain_for_next,
    should_count_for_odometer,
    runtime_template_errors,
)


CONTRACT = """; SPOOLMANAGER_CONTRACT_BEGIN
; spoolmanager_schema = 1
; spoolmanager_material = PETG
; spoolmanager_material_key = petg
; spoolmanager_color = Black
; spoolmanager_color_key = black
; spoolmanager_color_hex = #101010
; spoolmanager_required_g = 42.731
; spoolmanager_tool_count = 1
; spoolmanager_source = order-manager
; SPOOLMANAGER_CONTRACT_END
"""


class FakeSpool(object):
    def __init__(self, spool_id, material, color_name, color, remaining):
        self.databaseId = spool_id
        self.displayName = "spool-%s" % spool_id
        self.material = material
        self.colorName = color_name
        self.color = color
        self.remainingWeight = remaining
        self.isActive = True


class MmuRoutingTests(unittest.TestCase):
    def setUp(self):
        self.contract = parse_contract_text(CONTRACT)
        self.slots = [
            build_slot(0, FakeSpool(10, "PLA", "Black", "#101010", 500)),
            build_slot(1, FakeSpool(11, "PETG", "Black", "#101010", 20)),
            build_slot(2, FakeSpool(12, "PETG", "Black", "#101010", 500)),
            build_slot(3, FakeSpool(13, "PETG", "White", "#FFFFFF", 500)),
        ]

    def test_contract_and_slot_resolution_require_exact_identity_and_weight(self):
        self.assertTrue(self.contract["valid"])
        decision = select_slot(self.contract, self.slots)
        self.assertTrue(decision["ok"])
        self.assertEqual(decision["slot"], 2)

    def test_live_contract_requires_all_bounded_runtime_markers(self):
        all_markers = "\n".join([
            "@SPOOLMANAGER PURGE_AREA_BEGIN",
            "@SPOOLMANAGER PURGE_AREA_END",
            "@SPOOLMANAGER START_SEQUENCE_BEGIN",
            "@SPOOLMANAGER START_SEQUENCE_END",
            "@SPOOLMANAGER END_SEQUENCE_BEGIN",
            "@SPOOLMANAGER END_SEQUENCE_END",
        ])
        self.assertEqual(missing_runtime_markers(all_markers), [])
        self.assertIn("@SPOOLMANAGER END_SEQUENCE_END", missing_runtime_markers(all_markers.replace("@SPOOLMANAGER END_SEQUENCE_END", "")))

    def test_live_template_requires_every_command_that_fresh_mode_rewrites(self):
        template = """@SPOOLMANAGER PURGE_AREA_BEGIN
G29 P1 X0 Y0 W50 H20 C
@SPOOLMANAGER PURGE_AREA_END
@SPOOLMANAGER START_SEQUENCE_BEGIN
M569 S0 E
G0 X25 E4 F500
G0 X35 E4 F650
G0 X45 E4 F800
G0 X48 Z0.05 F8000
G0 X51 Z0.2 F8000
@SPOOLMANAGER START_SEQUENCE_END
@SPOOLMANAGER END_SEQUENCE_BEGIN
G4 ; wait
@SPOOLMANAGER END_SEQUENCE_END
"""
        self.assertEqual(runtime_template_errors(template.splitlines()), [])
        self.assertIn("start_m569", runtime_template_errors(template.replace("M569 S0 E", "M569 S1 E").splitlines()))

    def test_loaded_matching_slot_is_preferred(self):
        self.slots.append(build_slot(4, FakeSpool(14, "PETG", "Black", "#101010", 500)))
        decision = select_slot(self.contract, self.slots, loaded_slot=4)
        self.assertEqual(decision["slot"], 4)

    def test_dry_run_never_rewrites_commands(self):
        decision = select_slot(self.contract, self.slots)
        session = MmuRoutingSession()
        session.configure(True, True, self.contract, decision, STATE_UNLOADED)
        session.handle_marker("PURGE_AREA_BEGIN")
        self.assertIsNone(session.rewrite("G29 P1 X0 Y0 W50 H20 C"))

    def test_fresh_load_rewrites_only_marked_regions(self):
        decision = select_slot(self.contract, self.slots)
        session = MmuRoutingSession()
        session.configure(True, False, self.contract, decision, STATE_UNLOADED)

        self.assertIsNone(session.rewrite("G29 P1 X0 Y0 W50 H20 C"))
        session.handle_marker("PURGE_AREA_BEGIN")
        self.assertEqual(session.rewrite("G29 P1 X0 Y0 W50 H20 C")[0], "G29 P1 X0 Y0 W130 H20 C")
        session.handle_marker("PURGE_AREA_END")

        session.handle_marker("START_SEQUENCE_BEGIN")
        expanded = session.rewrite("M569 S0 E ; spreadcycle")
        self.assertEqual(expanded[-2][0], "T2 ; SM_PURPOSE=MMU_SELECT")
        self.assertIn("spoolmanager:mmu_select", expanded[-2][2])
        self.assertEqual(expanded[-1][0], "G1 E75 F1000 ; SM_PURPOSE=MMU_TRANSPORT")
        self.assertIn("spoolmanager:mmu_transport", expanded[-1][2])
        self.assertIn("X105 E36", session.rewrite("G0 X25 E4 F500 ; purge")[0])

    def test_retained_load_keeps_start_purge_and_skips_unload(self):
        decision = select_slot(self.contract, self.slots)
        session = MmuRoutingSession()
        session.configure(True, False, self.contract, decision, STATE_LOADED, loaded_slot=2, unload_at_end=False)
        self.assertFalse(session.fresh_load)
        session.handle_marker("START_SEQUENCE_BEGIN")
        self.assertIsNone(session.rewrite("M569 S0 E"))
        session.handle_marker("END_SEQUENCE_BEGIN")
        self.assertEqual(session.rewrite("G1 E-6 F100 ; jobox"), (None,))
        self.assertIsNone(session.rewrite("G4 ; wait"))

    def test_unload_is_inserted_once_before_wait_and_jobox_cooldown_is_removed(self):
        decision = select_slot(self.contract, self.slots)
        session = MmuRoutingSession()
        session.configure(True, False, self.contract, decision, STATE_UNLOADED, unload_at_end=True)
        session.handle_marker("END_SEQUENCE_BEGIN")
        self.assertEqual(session.rewrite("M104 S160 ; jobox"), (None,))
        rewritten = session.rewrite("G4 ; wait")
        self.assertEqual(rewritten[0][0], "M702 ; SM_PURPOSE=MMU_UNLOAD")
        self.assertIn("spoolmanager:mmu_unload", rewritten[0][2])
        self.assertEqual(rewritten[1], "G4 ; wait")
        self.assertIsNone(session.rewrite("G4 ; wait"))

    def test_continuousprint_repeated_set_is_its_own_next_path(self):
        state = {
            "active": True,
            "profile": "mk4",
            "queues": [{
                "name": "local", "rank": 1, "active_set": 101,
                "jobs": [{
                    "id": 1, "remaining": 1, "draft": False,
                    "sets": [{"id": 101, "path": "black.gcode", "remaining": 2, "count": 2, "profiles": []}],
                }],
            }],
        }
        self.assertEqual(continuousprint_next_path(state), "black.gcode")

    def test_continuousprint_lookahead_uses_next_set_then_next_job(self):
        state = {
            "active": True,
            "profile": "mk4",
            "queues": [{
                "name": "local", "rank": 1, "active_set": 101,
                "jobs": [
                    {"id": 1, "remaining": 1, "draft": False, "sets": [
                        {"id": 101, "path": "black.gcode", "remaining": 1, "count": 1, "profiles": []},
                        {"id": 102, "path": "white.gcode", "remaining": 1, "count": 1, "profiles": []},
                    ]},
                    {"id": 2, "remaining": 1, "draft": False, "sets": [
                        {"id": 201, "path": "later.gcode", "remaining": 1, "count": 1, "profiles": []},
                    ]},
                ],
            }],
        }
        self.assertEqual(continuousprint_next_path(state), "white.gcode")
        state["queues"][0]["jobs"][0]["sets"][1]["remaining"] = 0
        self.assertEqual(continuousprint_next_path(state), "later.gcode")

    def test_retention_requires_same_physical_spool_and_combined_weight(self):
        decision = select_slot(self.contract, self.slots)
        self.assertTrue(should_retain_for_next(self.contract, decision, self.contract, self.slots))
        self.slots[2]["remaining_g"] = 80
        self.assertFalse(should_retain_for_next(self.contract, decision, self.contract, self.slots))

    def test_odometer_ignores_runtime_tool_and_transport_but_counts_extra_purge(self):
        self.assertFalse(should_count_for_odometer("T2", {"spoolmanager:mmu_select"}))
        self.assertFalse(should_count_for_odometer("G1 E75 F1000", {"spoolmanager:mmu_transport"}))
        self.assertTrue(should_count_for_odometer("G0 X105 E36 F500", {"spoolmanager:mmu_extra_purge"}))


if __name__ == "__main__":
    unittest.main()
