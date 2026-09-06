import os
import sys
import unittest


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mmu_routing import (
    MmuRoutingSession,
    STATE_LOADED,
    STATE_UNKNOWN,
    STATE_UNLOADED,
    build_slot,
    classify_mmu_serial_line,
    mmu_completion_state,
    continuousprint_next_path,
    missing_runtime_markers,
    parse_contract_text,
    routing_bypass_reason,
    maintenance_bypass_files,
    select_slot,
    spool_accounting_targets,
    should_retain_for_next,
    should_count_for_odometer,
    runtime_template_errors,
    unload_lift_target_text,
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

    def test_order_camelcase_color_matches_inventory_spaces_without_fuzzy_matching(self):
        requirement = dict(self.contract, material_key="pla", color="pastelBlue",
                           color_key="pastelblue", color_hex="")
        for name in ["pastel blue", "Pastel-Blue", "pastelBlue"]:
            slots = [build_slot(0, FakeSpool(923, "PLA", name, "#b8d6fc", 500))]
            self.assertTrue(select_slot(requirement, slots)["ok"], name)
        for material, name in [("PLA", "blue"), ("PLA", "pastel green"), ("PETG", "pastel blue")]:
            slots = [build_slot(0, FakeSpool(923, material, name, "#b8d6fc", 500))]
            self.assertFalse(select_slot(requirement, slots)["ok"])

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
        template = """M190 S60
M109 S230
@SPOOLMANAGER PURGE_AREA_BEGIN
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

        session.rewrite("M190 S60")
        session.rewrite("M109 S230")
        self.assertIsNone(session.rewrite("G29 P1 X0 Y0 W50 H20 C"))
        session.handle_marker("PURGE_AREA_BEGIN")
        self.assertEqual(session.rewrite("G29 P1 X0 Y0 W50 H20 C")[0], "G29 P1 X0 Y0 W235 H20 C")
        session.handle_marker("PURGE_AREA_END")

        session.handle_marker("START_SEQUENCE_BEGIN")
        expanded = session.rewrite("M569 S0 E ; spreadcycle")
        self.assertEqual(expanded[0], "M569 S0 E")
        self.assertEqual(expanded[-2][0], "T2")
        self.assertIn("spoolmanager:mmu_select", expanded[-2][2])
        self.assertEqual(expanded[-1][0], "G1 E17 F1000")
        self.assertIn("spoolmanager:mmu_transport", expanded[-1][2])
        self.assertIn("X205 E76", session.rewrite("G0 X25 E4 F500 ; purge")[0])
        self.assertEqual(session.rewrite("G0 X35 E4 F650 ; purge")[0], "G0 X215 E4 F650")
        purge_tail = session.rewrite("G0 X45 E4 F800 ; purge")
        purge_commands = [entry if isinstance(entry, str) else entry[0] for entry in purge_tail]
        self.assertEqual(purge_commands, [
            "G0 X225 E4 F800",
            "G0 Y-2 E0.8 F800",
            "G0 X35 E76 F500",
            "G0 X25 E4 F650",
            "G0 X15 E4 F800",
        ])
        self.assertIn("spoolmanager:mmu_extra_purge", purge_tail[1][2])
        self.assertIn("spoolmanager:mmu_extra_purge", purge_tail[2][2])
        self.assertEqual(session.rewrite("G0 X48 Z0.05 F8000")[0], "G0 X12 Z0.05 F8000")
        self.assertEqual(session.rewrite("G0 X51 Z0.2 F8000")[0], "G0 X9 Z0.2 F8000")
        self.assertEqual(session.extra_purge_mm, 156.8)
        for injected in expanded[1:]:
            self.assertNotIn(";", injected[0])

    def test_purge_pass_setting_supports_one_to_three_passes(self):
        decision = select_slot(self.contract, self.slots)

        one_pass = MmuRoutingSession()
        one_pass.configure(
            True, False, self.contract, decision, STATE_UNLOADED, purge_passes=1
        )
        one_pass.handle_marker("START_SEQUENCE_BEGIN")
        self.assertEqual(one_pass.rewrite("G0 X45 E4 F800"), ["G0 X225 E4 F800"])
        self.assertEqual(one_pass.rewrite("G0 X48 Z0.05 F8000")[0], "G0 X228 Z0.05 F8000")
        self.assertEqual(one_pass.extra_purge_mm, 72.0)

        three_pass = MmuRoutingSession()
        three_pass.configure(
            True, False, self.contract, decision, STATE_UNLOADED, purge_passes=9
        )
        self.assertEqual(three_pass.purge_passes, 3)
        three_pass.handle_marker("START_SEQUENCE_BEGIN")
        purge_tail = three_pass.rewrite("G0 X45 E4 F800")
        commands = [entry if isinstance(entry, str) else entry[0] for entry in purge_tail]
        self.assertEqual(commands[-4:], [
            "G0 Y0 E0.8 F800",
            "G0 X205 E76 F500",
            "G0 X215 E4 F650",
            "G0 X225 E4 F800",
        ])
        self.assertEqual(three_pass.rewrite("G0 X48 Z0.05 F8000")[0], "G0 X228 Z0.05 F8000")
        self.assertEqual(three_pass.extra_purge_mm, 241.6)

    def test_unknown_state_injects_sensor_aware_recovery_before_select(self):
        decision = select_slot(self.contract, self.slots)
        session = MmuRoutingSession()
        session.configure(True, False, self.contract, decision, STATE_UNKNOWN)
        self.assertTrue(session.active)
        self.assertTrue(session.recovery_required)
        session.rewrite("M190 S60")
        session.rewrite("M109 S230")
        session.handle_marker("START_SEQUENCE_BEGIN")
        expanded = session.rewrite("M569 S0 E")
        commands = [entry if isinstance(entry, str) else entry[0] for entry in expanded]
        self.assertLess(commands.index("M702 W255"), commands.index("T2"))
        self.assertEqual(commands[commands.index("M702 W255") + 1:commands.index("T2")], [
            "M140 S60", "M104 S230", "M190 S60", "M109 S230", "M83", "G92 E0", "M569 S0 E",
        ])
        recovery = expanded[commands.index("M702 W255")]
        self.assertIn("spoolmanager:mmu_recovery", recovery[2])

    def test_maintenance_files_and_explicit_marker_bypass_routing(self):
        self.assertEqual(routing_bypass_reason("Swap Plate with Doors.gcode"), "maintenance_filename")
        self.assertEqual(routing_bypass_reason("Jobox Load Plate.gcode"), "maintenance_filename")
        self.assertEqual(routing_bypass_reason("Jobox Eject Plate.gcode"), "maintenance_filename")
        self.assertEqual(routing_bypass_reason("uploads/JOBOX LOAD PLATE.GCODE"), "maintenance_filename")
        self.assertEqual(
            routing_bypass_reason("custom.gcode", "; SPOOLMANAGER_ROUTING_BYPASS = maintenance"),
            "marker:maintenance",
        )
        self.assertIsNone(routing_bypass_reason("ordinary.gcode"))

        session = MmuRoutingSession()
        session.configure_bypass(True, False, "maintenance_filename")
        self.assertTrue(session.allow_print)
        self.assertFalse(session.active)
        self.assertIsNone(session.rewrite("T0"))

    def test_new_maintenance_files_survive_an_older_saved_bypass_list(self):
        merged = maintenance_bypass_files(["Swap Plate with Doors.gcode", "Custom Service.gcode"])
        self.assertIn("Jobox Load Plate.gcode", merged)
        self.assertIn("Jobox Eject Plate.gcode", merged)
        self.assertIn("Custom Service.gcode", merged)

    def test_continuousprint_automation_files_bypass_routing(self):
        self.assertEqual(
            routing_bypass_reason("ContinuousPrint/tmp/continuousprint_success.gcode"),
            "continuousprint_automation",
        )
        self.assertEqual(
            routing_bypass_reason("ContinuousPrint/tmp/continuousprint_start_print.gcode"),
            "continuousprint_automation",
        )
        self.assertIsNone(routing_bypass_reason("uploads/continuousprint_success.gcode"))

    def test_mk4_serial_progress_is_classified_without_prusammu_dependency(self):
        self.assertEqual(classify_mmu_serial_line("MMU2:Feeding to FSensor"), "LOADING")
        self.assertEqual(classify_mmu_serial_line("MMU2:Retract from FINDA"), "UNLOADING")
        self.assertEqual(classify_mmu_serial_line("MMU2:Disengaging idler"), "ACTION_DONE")
        self.assertEqual(classify_mmu_serial_line("MMU2:ERR Help filament"), "ERROR")
        self.assertIsNone(classify_mmu_serial_line("ok"))

    def test_mmu_completion_after_an_error_stays_unknown(self):
        self.assertEqual(mmu_completion_state("LOADING", 2), (STATE_LOADED, 2))
        self.assertEqual(mmu_completion_state("UNLOADING", 2), (STATE_UNLOADED, None))
        self.assertEqual(
            mmu_completion_state("LOADING", 2, action_uncertain=True),
            (STATE_UNKNOWN, None),
        )
        self.assertEqual(
            mmu_completion_state("UNLOADING", 2, action_uncertain=True),
            (STATE_UNKNOWN, None),
        )

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
        session.configure(
            True, False, self.contract, decision, STATE_UNLOADED,
            unload_at_end=True, unload_lift_z=38.2
        )
        session.handle_marker("END_SEQUENCE_BEGIN")
        self.assertEqual(session.rewrite("M104 S160 ; jobox"), (None,))
        self.assertEqual(session.rewrite("M104 S0 ; turn off temperature"), (None,))
        rewritten = session.rewrite("G4 ; wait")
        self.assertEqual([entry[0] for entry in rewritten[:2]], ["G90", "G1 Z38.2 F720"])
        for lift_command in rewritten[:2]:
            self.assertIn("spoolmanager:mmu_unload_lift", lift_command[2])
        self.assertEqual(rewritten[2][0], "M702")
        self.assertIn("spoolmanager:mmu_unload", rewritten[2][2])
        self.assertEqual(rewritten[3][0], "M104 S0")
        self.assertIn("spoolmanager:mmu_unload_shutdown", rewritten[3][2])
        self.assertEqual(rewritten[4], "G4")
        self.assertIsNone(session.rewrite("G4 ; wait"))

    def test_unload_lift_is_absolute_and_capped_to_printer_height(self):
        template = """@SPOOLMANAGER END_SEQUENCE_BEGIN
G1 Z%s F300 ; sliced capped end lift
G4 ; wait
@SPOOLMANAGER END_SEQUENCE_END
; max_print_height = 220
"""
        self.assertEqual(unload_lift_target_text(template % "23.2"), 38.2)
        self.assertEqual(unload_lift_target_text(template % "213"), 220.0)
        self.assertIsNone(unload_lift_target_text(template % "220"))
        self.assertIsNone(unload_lift_target_text(template.replace("; max_print_height = 220", "") % "23.2"))

    def test_retained_filament_does_not_defer_hotend_shutdown(self):
        decision = select_slot(self.contract, self.slots)
        session = MmuRoutingSession()
        session.configure(True, False, self.contract, decision, STATE_LOADED, loaded_slot=2, unload_at_end=False)
        session.handle_marker("END_SEQUENCE_BEGIN")
        self.assertIsNone(session.rewrite("M104 S0 ; turn off temperature"))

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

    def test_continuousprint_lookahead_repairs_missing_active_set_from_live_queue(self):
        state = {
            "active": True,
            "profile": "mk4",
            "queues": [{
                "name": "local", "rank": 1, "active_set": None,
                "jobs": [
                    {"id": 1, "remaining": 1, "draft": False, "acquired": True, "sets": [
                        {"id": 101, "path": "first.gcode", "remaining": 1, "count": 1, "profiles": []},
                    ]},
                    {"id": 2, "remaining": 1, "draft": False, "acquired": False, "sets": [
                        {"id": 201, "path": "second.gcode", "remaining": 1, "count": 1, "profiles": []},
                    ]},
                ],
            }],
        }
        self.assertEqual(
            continuousprint_next_path(state, active_set_id=101, active_queue_name="local"),
            "second.gcode",
        )
        self.assertEqual(
            continuousprint_next_path(state, current_path="first.gcode"),
            "second.gcode",
        )
        state["active"] = False
        state["queues"][0]["active_set"] = 999
        self.assertEqual(
            continuousprint_next_path(state, active_set_id=101, active_queue_name="local"),
            "second.gcode",
        )

    def test_retention_requires_same_physical_spool_and_combined_weight(self):
        decision = select_slot(self.contract, self.slots)
        self.assertTrue(should_retain_for_next(self.contract, decision, self.contract, self.slots))
        self.slots[2]["remaining_g"] = 80
        self.assertFalse(should_retain_for_next(self.contract, decision, self.contract, self.slots))

    def test_odometer_ignores_runtime_tool_and_transport_but_counts_extra_purge(self):
        self.assertFalse(should_count_for_odometer("T2", {"spoolmanager:mmu_select"}))
        self.assertFalse(should_count_for_odometer("G1 E17 F1000", {"spoolmanager:mmu_transport"}))
        self.assertTrue(should_count_for_odometer("G0 X205 E76 F500", {"spoolmanager:mmu_extra_purge"}))

    def test_live_single_nozzle_usage_is_charged_to_selected_mmu_position(self):
        self.assertEqual(spool_accounting_targets(5, True, False, 1), [(0, 1)])
        self.assertEqual(spool_accounting_targets(5, True, False, 4), [(0, 4)])
        self.assertEqual(spool_accounting_targets(5, True, False, None), [])
        self.assertEqual(spool_accounting_targets(5, True, False, 5), [])

    def test_dry_run_and_normal_prints_keep_standard_tool_accounting(self):
        expected = [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4)]
        self.assertEqual(spool_accounting_targets(5, True, True, 1), expected)
        self.assertEqual(spool_accounting_targets(5, False, False, None), expected)


if __name__ == "__main__":
    unittest.main()
