# coding=utf-8
from __future__ import absolute_import

import re
import unicodedata
import io


CONTRACT_SCHEMA = 1
STATE_UNKNOWN = "UNKNOWN"
STATE_UNLOADED = "UNLOADED"
STATE_LOADED = "LOADED"

DEFAULT_LOAD_DISTANCE_MM = 17.0
LEGACY_LOAD_DISTANCE_MM = 75.0
DEFAULT_PURGE_PASSES = 2
MIN_PURGE_PASSES = 1
MAX_PURGE_PASSES = 3
UNLOAD_EXTRA_LIFT_MM = 15.0
FIRST_PASS_EXTRA_PURGE_MM = 72.0
ADDITIONAL_PASS_PURGE_MM = 84.8
DEFAULT_MAINTENANCE_BYPASS_FILES = (
    "Swap Plate with Doors.gcode",
    "Swap Plate with Doors-2.gcode",
    "Jobox Load Plate.gcode",
    "Jobox Eject Plate.gcode",
)
CONTINUOUSPRINT_AUTOMATION_DIR = "continuousprint/tmp/"

REGION_NONE = None
REGION_PURGE_AREA = "PURGE_AREA"
REGION_START = "START_SEQUENCE"
REGION_END = "END_SEQUENCE"

REQUIRED_RUNTIME_MARKERS = (
    "@SPOOLMANAGER PURGE_AREA_BEGIN",
    "@SPOOLMANAGER PURGE_AREA_END",
    "@SPOOLMANAGER START_SEQUENCE_BEGIN",
    "@SPOOLMANAGER START_SEQUENCE_END",
    "@SPOOLMANAGER END_SEQUENCE_BEGIN",
    "@SPOOLMANAGER END_SEQUENCE_END",
)


def maintenance_bypass_files(configured=None):
    """Merge built-in maintenance jobs with any names saved in older settings."""
    merged = []
    seen = set()
    for value in list(DEFAULT_MAINTENANCE_BYPASS_FILES) + list(configured or []):
        name = str(value or "").strip()
        key = name.lower()
        if name and key not in seen:
            merged.append(name)
            seen.add(key)
    return merged


def parse_routing_bypass_text(text):
    """Return the optional routing-bypass reason embedded in a G-code header."""
    for raw_line in str(text or "").splitlines():
        match = re.match(
            r"^;\s*SPOOLMANAGER_ROUTING_BYPASS\s*=\s*([a-z0-9_-]+)\s*$",
            raw_line.strip(),
            re.I,
        )
        if match:
            return match.group(1).lower()
    return None


def routing_bypass_reason(name, text=None, allowed_names=None):
    """Return a safe explicit bypass reason, or None when routing is required."""
    normalized = str(name or "").replace("\\", "/").strip().lower().lstrip("/")
    filename = normalized.rsplit("/", 1)[-1]
    if normalized.startswith(CONTINUOUSPRINT_AUTOMATION_DIR) and filename.endswith(".gcode"):
        return "continuousprint_automation"
    configured = allowed_names if allowed_names is not None else DEFAULT_MAINTENANCE_BYPASS_FILES
    allowed = set(str(value or "").strip().lower() for value in configured if str(value or "").strip())
    if filename and filename in allowed:
        return "maintenance_filename"
    marker = parse_routing_bypass_text(text)
    if marker:
        return "marker:%s" % marker
    return None


def routing_bypass_reason_file(path, name=None, allowed_names=None, max_bytes=65536):
    filename_reason = routing_bypass_reason(name or path, allowed_names=allowed_names)
    if filename_reason:
        return filename_reason
    with open(path, "rb") as handle:
        raw = handle.read(int(max_bytes))
    try:
        text = raw.decode("utf-8", errors="replace")
    except TypeError:
        text = raw.decode("utf-8", "replace")
    return routing_bypass_reason(name or path, text=text, allowed_names=allowed_names)


def classify_mmu_serial_line(line):
    """Classify the MK4 MMU progress messages also used by Prusa MMU."""
    text = str(line or "")
    if any(value in text for value in (
        "MMU2:Command Error",
        "MMU2:ERR Help filament",
        "MMU2:ERR Internal",
        "MMU2:ERR TMC failed",
    )):
        return "ERROR"
    if any(value in text for value in (
        "MMU2:Feeding to FINDA",
        "MMU2:Feeding to extruder",
        "MMU2:Feeding to FSensor",
    )):
        return "LOADING"
    if any(value in text for value in (
        "MMU2:Unloading to FINDA",
        "MMU2:Retract from FINDA",
    )):
        return "UNLOADING"
    if "MMU2:Disengaging idler" in text:
        return "ACTION_DONE"
    return None


def mmu_completion_state(pending_action, pending_slot=None, action_uncertain=False):
    """Return a trusted physical state only when the whole action was error-free."""
    if action_uncertain:
        return STATE_UNKNOWN, None
    action = str(pending_action or "").upper()
    if action == "UNLOADING":
        return STATE_UNLOADED, None
    if action == "LOADING":
        try:
            slot = int(pending_slot)
        except Exception:
            return STATE_UNKNOWN, None
        if 0 <= slot <= 4:
            return STATE_LOADED, slot
    return STATE_UNKNOWN, None


def normalize_key(value):
    text = value if isinstance(value, str) else str(value or "")
    text = unicodedata.normalize("NFKD", text)
    try:
        text = text.encode("ascii", "ignore").decode("ascii")
    except Exception:
        pass
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def normalize_hex(value):
    text = str(value or "").strip().upper()
    if re.match(r"^#[0-9A-F]{6}$", text):
        return text
    if re.match(r"^[0-9A-F]{6}$", text):
        return "#" + text
    return ""


def parse_contract_text(text):
    values = {}
    inside = False
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if line == "; SPOOLMANAGER_CONTRACT_BEGIN":
            inside = True
            continue
        if line == "; SPOOLMANAGER_CONTRACT_END":
            break
        if not inside:
            continue
        match = re.match(r"^;\s*spoolmanager_([a-z0-9_]+)\s*=\s*(.*?)\s*$", line, re.I)
        if match:
            values[match.group(1).lower()] = match.group(2).strip()

    try:
        schema = int(values.get("schema") or 0)
    except Exception:
        schema = 0
    try:
        required_g = max(0.0, float(values.get("required_g") or 0))
    except Exception:
        required_g = 0.0
    try:
        tool_count = int(values.get("tool_count") or 0)
    except Exception:
        tool_count = 0

    material = values.get("material") or ""
    color = values.get("color") or ""
    result = {
        "valid": False,
        "schema": schema,
        "material": material,
        "material_key": values.get("material_key") or normalize_key(material),
        "color": color,
        "color_key": values.get("color_key") or normalize_key(color),
        "color_hex": normalize_hex(values.get("color_hex") or color),
        "required_g": required_g,
        "tool_count": tool_count,
        "source": values.get("source") or "unknown",
        "error": None,
    }
    if schema != CONTRACT_SCHEMA:
        result["error"] = "unsupported contract schema"
    elif tool_count != 1:
        result["error"] = "single-nozzle routing requires exactly one used tool"
    elif not result["material_key"] or not result["color_key"]:
        result["error"] = "missing material or color"
    elif required_g <= 0:
        result["error"] = "missing required filament weight"
    else:
        result["valid"] = True
    return result


def parse_contract_file(path, max_bytes=65536):
    with open(path, "rb") as handle:
        raw = handle.read(int(max_bytes))
    try:
        text = raw.decode("utf-8", errors="replace")
    except TypeError:
        text = raw.decode("utf-8", "replace")
    return parse_contract_text(text)


def missing_runtime_markers(text):
    source = str(text or "")
    return [marker for marker in REQUIRED_RUNTIME_MARKERS if marker not in source]


def missing_runtime_markers_file(path, chunk_bytes=1024 * 1024):
    missing = set(REQUIRED_RUNTIME_MARKERS)
    tail = b""
    with open(path, "rb") as handle:
        while missing:
            chunk = handle.read(int(chunk_bytes))
            if not chunk:
                break
            data = tail + chunk
            for marker in list(missing):
                if marker.encode("ascii") in data:
                    missing.remove(marker)
            tail = data[-128:]
    return [marker for marker in REQUIRED_RUNTIME_MARKERS if marker in missing]


def runtime_template_errors(lines):
    region = REGION_NONE
    found = set()
    for raw_line in lines:
        line = str(raw_line or "").strip()
        if line == "@SPOOLMANAGER PURGE_AREA_BEGIN":
            region = REGION_PURGE_AREA
            found.add("purge_begin")
            continue
        if line == "@SPOOLMANAGER PURGE_AREA_END":
            region = REGION_NONE
            found.add("purge_end")
            continue
        if line == "@SPOOLMANAGER START_SEQUENCE_BEGIN":
            region = REGION_START
            found.add("start_begin")
            continue
        if line == "@SPOOLMANAGER START_SEQUENCE_END":
            region = REGION_NONE
            found.add("start_end")
            continue
        if line == "@SPOOLMANAGER END_SEQUENCE_BEGIN":
            region = REGION_END
            found.add("end_begin")
            continue
        if line == "@SPOOLMANAGER END_SEQUENCE_END":
            region = REGION_NONE
            found.add("end_end")
            continue
        upper = line.upper()
        if "start_m569" not in found and re.match(r"^M190\s+S[-+]?[0-9]+(?:\.[0-9]+)?\b", upper):
            found.add("recovery_m190")
        if "start_m569" not in found and re.match(r"^M109(?:\s+T\d+)?\s+S[-+]?[0-9]+(?:\.[0-9]+)?\b", upper):
            found.add("recovery_m109")
        if region == REGION_PURGE_AREA and re.match(r"^G29\s+P1\s+X0\s+Y0\s+W50\s+H20\s+C\b", upper):
            found.add("purge_w50")
        elif region == REGION_START:
            checks = (
                ("start_m569", r"^M569\s+S0\s+E\b"),
                ("purge_x25", r"^G0\s+X25\s+E4\s+F500\b"),
                ("purge_x35", r"^G0\s+X35\s+E4\s+F650\b"),
                ("purge_x45", r"^G0\s+X45\s+E4\s+F800\b"),
                ("wipe_x48", r"^G0\s+X48\s+Z0\.05\s+F8000\b"),
                ("wipe_x51", r"^G0\s+X51\s+Z0\.2\s+F8000\b"),
            )
            for key, pattern in checks:
                if re.match(pattern, upper):
                    found.add(key)
        elif region == REGION_END and re.match(r"^G4(?:\s|;|$)", upper):
            found.add("end_wait")
    required = set([
        "purge_begin", "purge_end", "start_begin", "start_end", "end_begin", "end_end",
        "recovery_m190", "recovery_m109", "purge_w50", "start_m569",
        "purge_x25", "purge_x35", "purge_x45", "wipe_x48", "wipe_x51", "end_wait",
    ])
    return sorted(required - found)


def runtime_template_errors_file(path):
    with io.open(path, "r", encoding="utf-8", errors="replace") as handle:
        return runtime_template_errors(handle)


def _unload_lift_target_lines(lines, extra_lift_mm):
    in_end = False
    end_z = None
    max_print_height = None
    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
    for raw_line in lines:
        line = raw_line.strip()
        if line == "@SPOOLMANAGER END_SEQUENCE_BEGIN":
            in_end = True
            continue
        if line == "@SPOOLMANAGER END_SEQUENCE_END":
            in_end = False
            continue
        height_match = re.match(
            r"^;\s*max_print_height\s*=\s*(%s)\s*$" % number,
            line,
            re.I,
        )
        if height_match:
            max_print_height = float(height_match.group(1))
        if in_end:
            if re.match(r"^G4(?:\s|;|$)", line, re.I):
                in_end = False
                continue
            if re.match(r"^G[01]\b", line, re.I):
                z_match = re.search(r"(?:^|\s)Z(%s)(?:\s|;|$)" % number, line, re.I)
                if z_match:
                    end_z = float(z_match.group(1))
    if end_z is None or max_print_height is None:
        return None
    target = min(end_z + float(extra_lift_mm), max_print_height)
    return target if target > end_z + 0.0005 else None


def unload_lift_target_text(text, extra_lift_mm=UNLOAD_EXTRA_LIFT_MM):
    """Return a capped absolute Z target, or None when no extra lift is safe."""
    return _unload_lift_target_lines(
        str(text or "").splitlines(),
        extra_lift_mm,
    )


def unload_lift_target_file(path, extra_lift_mm=UNLOAD_EXTRA_LIFT_MM):
    with io.open(path, "r", encoding="utf-8", errors="replace") as handle:
        return _unload_lift_target_lines(handle, extra_lift_mm)


def build_slot(slot_index, spool):
    if spool is None:
        return {"slot": int(slot_index), "spool_id": None, "active": False}
    return {
        "slot": int(slot_index),
        "spool_id": getattr(spool, "databaseId", None),
        "display_name": getattr(spool, "displayName", None),
        "material": getattr(spool, "material", None),
        "material_key": normalize_key(getattr(spool, "material", None)),
        "color_name": getattr(spool, "colorName", None),
        "color_key": normalize_key(getattr(spool, "colorName", None)),
        "color": getattr(spool, "color", None),
        "color_hex": normalize_hex(getattr(spool, "color", None)),
        "remaining_g": getattr(spool, "remainingWeight", None),
        "active": getattr(spool, "isActive", True) is not False,
    }


def _slot_matches(requirement, slot):
    if not slot or not slot.get("active") or slot.get("spool_id") is None:
        return False
    if normalize_key(slot.get("material_key") or slot.get("material")) != requirement.get("material_key"):
        return False
    required_hex = normalize_hex(requirement.get("color_hex"))
    slot_hex = normalize_hex(slot.get("color_hex") or slot.get("color"))
    if required_hex and slot_hex and required_hex == slot_hex:
        return True
    required_key = requirement.get("color_key") or normalize_key(requirement.get("color"))
    slot_keys = set([
        normalize_key(slot.get("color_key") or slot.get("color_name")),
        normalize_key(slot.get("color")),
    ])
    return required_key in slot_keys


def select_slot(requirement, slots, loaded_slot=None, reserve_g=0.0):
    if not requirement or not requirement.get("valid"):
        return {"ok": False, "reason": "invalid_contract", "slot": None}
    needed = float(requirement.get("required_g") or 0) + max(0.0, float(reserve_g or 0))
    matches = []
    insufficient = []
    for slot in slots or []:
        if not _slot_matches(requirement, slot):
            continue
        remaining = slot.get("remaining_g")
        if remaining is None or float(remaining) < needed:
            insufficient.append(slot)
        else:
            matches.append(slot)
    if not matches:
        return {
            "ok": False,
            "reason": "insufficient_filament" if insufficient else "no_matching_slot",
            "slot": None,
            "required_g": needed,
            "matching_slots": [entry.get("slot") for entry in insufficient],
        }
    matches.sort(key=lambda entry: (0 if entry.get("slot") == loaded_slot else 1, entry.get("slot")))
    chosen = matches[0]
    return {
        "ok": True,
        "reason": None,
        "slot": chosen.get("slot"),
        "spool_id": chosen.get("spool_id"),
        "required_g": needed,
        "matching_slots": [entry.get("slot") for entry in matches],
    }


def continuousprint_next_path(state_raw, active_set_id=None, active_queue_name=None, current_path=None):
    state = state_raw or {}
    if not isinstance(state, dict) or (not state.get("active") and active_set_id is None and not current_path):
        return None
    queues = list(state.get("queues") or [])
    queues.sort(key=lambda queue: float(queue.get("rank") or 0))
    profile = str(state.get("profile") or "")

    def printable(set_data, use_count=False):
        profiles = list(set_data.get("profiles") or [])
        amount = set_data.get("count") if use_count else set_data.get("remaining")
        try:
            amount = int(amount or 0)
        except Exception:
            amount = 0
        return amount > 0 and (not profiles or profile in profiles) and not set_data.get("missing_file")

    active_queue_index = None
    active_job_index = None
    active_set_index = None
    for queue_index, queue in enumerate(queues):
        active_set = queue.get("active_set")
        if active_set_id is not None:
            queue_name = str(queue.get("name") or "")
            if active_queue_name is None or queue_name == str(active_queue_name):
                active_set = active_set_id
        if active_set is None:
            continue
        for job_index, job in enumerate(queue.get("jobs") or []):
            for set_index, set_data in enumerate(job.get("sets") or []):
                if str(set_data.get("id")) == str(active_set):
                    active_queue_index = queue_index
                    active_job_index = job_index
                    active_set_index = set_index
                    break
            if active_set_index is not None:
                break
        if active_set_index is not None:
            break
    if active_set_index is None and current_path:
        normalized_current_path = str(current_path).replace("\\", "/").lstrip("/")
        candidates = []
        for queue_index, queue in enumerate(queues):
            if active_queue_name is not None and str(queue.get("name") or "") != str(active_queue_name):
                continue
            for job_index, job in enumerate(queue.get("jobs") or []):
                for set_index, set_data in enumerate(job.get("sets") or []):
                    set_path = str(set_data.get("path") or "").replace("\\", "/").lstrip("/")
                    if set_path == normalized_current_path:
                        # Prefer the acquired job when duplicate paths are queued.
                        candidates.append((0 if job.get("acquired") else 1, queue_index, job_index, set_index))
        if candidates:
            _, active_queue_index, active_job_index, active_set_index = sorted(candidates)[0]
    if active_set_index is None:
        return None

    current_queue = queues[active_queue_index]
    current_job = (current_queue.get("jobs") or [])[active_job_index]
    current_sets = current_job.get("sets") or []
    current_set = current_sets[active_set_index]
    try:
        if printable(current_set) and int(current_set.get("remaining") or 0) > 1:
            return current_set.get("path")
    except Exception:
        pass
    for set_data in current_sets[active_set_index + 1:]:
        if printable(set_data):
            return set_data.get("path")
    try:
        job_remaining = int(current_job.get("remaining") or 0)
    except Exception:
        job_remaining = 0
    if job_remaining > 1:
        for set_data in current_sets:
            if printable(set_data, use_count=True):
                return set_data.get("path")

    def first_path_in_jobs(jobs):
        for job in jobs:
            if job.get("draft"):
                continue
            try:
                if int(job.get("remaining") or 0) <= 0:
                    continue
            except Exception:
                continue
            for set_data in job.get("sets") or []:
                if printable(set_data):
                    return set_data.get("path")
        return None

    path = first_path_in_jobs((current_queue.get("jobs") or [])[active_job_index + 1:])
    if path:
        return path
    for queue in queues[active_queue_index + 1:]:
        path = first_path_in_jobs(queue.get("jobs") or [])
        if path:
            return path
    return None


def should_retain_for_next(current_requirement, current_decision, next_requirement, slots, reserve_g=0.0):
    if not current_decision or not current_decision.get("ok"):
        return False
    slot_number = current_decision.get("slot")
    slot = next((entry for entry in (slots or []) if entry.get("slot") == slot_number), None)
    if not slot or not _slot_matches(next_requirement, slot):
        return False
    try:
        available = float(slot.get("remaining_g"))
        needed = (
            float(current_requirement.get("required_g") or 0)
            + float(next_requirement.get("required_g") or 0)
            + max(0.0, float(reserve_g or 0))
        )
    except Exception:
        return False
    return available >= needed


def spool_accounting_targets(spool_count, mmu_active=False, dry_run=True, selected_slot=None):
    """Map logical G-code tools to the sidebar spool positions they consume."""
    try:
        count = max(0, int(spool_count or 0))
    except Exception:
        count = 0
    if mmu_active and not dry_run:
        try:
            slot = int(selected_slot)
        except Exception:
            return []
        if slot < 0 or slot >= count:
            return []
        # Single-nozzle files report all model extrusion as logical Tool 0, but
        # the selected physical MMU input may be any sidebar position.
        return [(0, slot)]
    return [(index, index) for index in range(count)]


class MmuRoutingSession(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.enabled = False
        self.dry_run = True
        self.region = REGION_NONE
        self.slot = None
        self.fresh_load = False
        self.recovery_required = False
        self.unload_at_end = True
        self.load_distance_mm = DEFAULT_LOAD_DISTANCE_MM
        self.purge_passes = DEFAULT_PURGE_PASSES
        self.extra_purge_mm = 0.0
        self.unload_injected = False
        self.recovery_injected = False
        self.restore_bed_wait = None
        self.restore_hotend_wait = None
        self.deferred_hotend_off = None
        self.unload_lift_z = None
        self.bypass = False
        self.bypass_reason = None
        self.contract = None
        self.decision = None
        self.error = None

    def configure(self, enabled, dry_run, contract, decision, loaded_state=STATE_UNKNOWN,
                  loaded_slot=None, unload_at_end=True, load_distance_mm=DEFAULT_LOAD_DISTANCE_MM,
                  purge_passes=DEFAULT_PURGE_PASSES, unload_lift_z=None):
        self.reset()
        self.enabled = bool(enabled)
        self.dry_run = bool(dry_run)
        self.contract = contract
        self.decision = decision
        self.unload_at_end = bool(unload_at_end)
        self.load_distance_mm = float(load_distance_mm or DEFAULT_LOAD_DISTANCE_MM)
        try:
            self.unload_lift_z = float(unload_lift_z) if unload_lift_z is not None else None
        except Exception:
            self.unload_lift_z = None
        try:
            self.purge_passes = max(MIN_PURGE_PASSES, min(MAX_PURGE_PASSES, int(purge_passes)))
        except Exception:
            self.purge_passes = DEFAULT_PURGE_PASSES
        if not self.enabled:
            return
        if not contract or not contract.get("valid"):
            self.error = "invalid_contract"
            return
        if not decision or not decision.get("ok"):
            self.error = (decision or {}).get("reason") or "no_slot"
            return
        self.slot = int(decision.get("slot"))
        retained = loaded_state == STATE_LOADED and loaded_slot == self.slot
        self.fresh_load = not retained
        self.recovery_required = bool(not self.dry_run and loaded_state == STATE_UNKNOWN)
        if self.fresh_load:
            # The first full-width pass adds 72 mm over the regular MK4 line;
            # each complete return pass adds another 84 mm at the MMU3 E/X ratio.
            self.extra_purge_mm = (
                FIRST_PASS_EXTRA_PURGE_MM
                + ADDITIONAL_PASS_PURGE_MM * (self.purge_passes - 1)
            )

    def configure_bypass(self, enabled, dry_run, reason):
        self.reset()
        self.enabled = bool(enabled)
        self.dry_run = bool(dry_run)
        self.bypass = True
        self.bypass_reason = str(reason or "maintenance")

    @property
    def active(self):
        return self.enabled and self.error is None and self.slot is not None

    @property
    def allow_print(self):
        return self.active or self.bypass

    def handle_marker(self, parameters):
        marker = str(parameters or "").strip().upper()
        if marker == "PURGE_AREA_BEGIN":
            self.region = REGION_PURGE_AREA
        elif marker == "PURGE_AREA_END":
            self.region = REGION_NONE
        elif marker == "START_SEQUENCE_BEGIN":
            self.region = REGION_START
        elif marker == "START_SEQUENCE_END":
            self.region = REGION_NONE
        elif marker == "END_SEQUENCE_BEGIN":
            self.region = REGION_END
        elif marker == "END_SEQUENCE_END":
            self.region = REGION_NONE

    def rewrite(self, cmd):
        if not self.active or self.dry_run:
            return None
        command = str(cmd or "")
        upper = command.upper()

        if re.match(r"^\s*M190\s+S[-+]?[0-9]+(?:\.[0-9]+)?\b", upper):
            self.restore_bed_wait = _without_inline_comment(command)
        if re.match(r"^\s*M109(?:\s+T\d+)?\s+S[-+]?[0-9]+(?:\.[0-9]+)?\b", upper):
            self.restore_hotend_wait = _without_inline_comment(command)

        if self.region == REGION_PURGE_AREA and self.fresh_load:
            if re.match(r"^\s*G29\s+P1\s+X0\s+Y0\s+W50\s+H20\s+C\b", upper):
                return (_without_inline_comment(re.sub(r"\bW50\b", "W235", command, count=1, flags=re.I)),)

        if self.region == REGION_START and self.fresh_load:
            if re.match(r"^\s*M569\s+S0\s+E\b", upper):
                setup = [
                    _without_inline_comment(command),
                    ("M708 A0x0b X5", None, {"spoolmanager:mmu_setup"}),
                    ("M708 A0x0d X140", None, {"spoolmanager:mmu_setup"}),
                    ("M708 A0x11 X140", None, {"spoolmanager:mmu_setup"}),
                    ("M708 A0x14 X20", None, {"spoolmanager:mmu_setup"}),
                    ("M708 A0x1e X12", None, {"spoolmanager:mmu_setup"}),
                ]
                if self.recovery_required:
                    self.recovery_injected = True
                    # W255 explicitly skips the interactive material/preheat dialog.
                    # The nozzle is already at the sliced first-layer temperature here.
                    setup.append(("M702 W255", None, {"spoolmanager:mmu_recovery"}))
                    # M702 can clear both temperature targets. Restore them before
                    # asking the MMU to feed filament into the hotend.
                    setup.extend([
                        (_wait_to_set_command(self.restore_bed_wait), None, {"spoolmanager:mmu_recovery_restore"}),
                        (_wait_to_set_command(self.restore_hotend_wait), None, {"spoolmanager:mmu_recovery_restore"}),
                        (self.restore_bed_wait, None, {"spoolmanager:mmu_recovery_restore"}),
                        (self.restore_hotend_wait, None, {"spoolmanager:mmu_recovery_restore"}),
                        ("M83", None, {"spoolmanager:mmu_recovery_restore"}),
                        ("G92 E0", None, {"spoolmanager:mmu_recovery_restore"}),
                        (_without_inline_comment(command), None, {"spoolmanager:mmu_recovery_restore"}),
                    ])
                setup.extend([
                    ("T%d" % self.slot, None, {"spoolmanager:mmu_select"}),
                    ("G1 E%s F1000" % _format_number(self.load_distance_mm), None, {"spoolmanager:mmu_transport"}),
                ])
                return setup
            replacements = (
                (r"^\s*G0\s+X25\s+E4\s+F500\b", "G0 X205 E76 F500"),
                (r"^\s*G0\s+X35\s+E4\s+F650\b", "G0 X215 E4 F650"),
            )
            for pattern, replacement in replacements:
                if re.match(pattern, upper):
                    return (replacement,)
            if re.match(r"^\s*G0\s+X45\s+E4\s+F800\b", upper):
                result = ["G0 X225 E4 F800"]
                for pass_index in range(2, self.purge_passes + 1):
                    y_position = -4.0 + 2.0 * (pass_index - 1)
                    result.append((
                        "G0 Y%s E0.8 F800" % _format_number(y_position),
                        None,
                        {"spoolmanager:mmu_extra_purge"},
                    ))
                    if pass_index % 2 == 0:
                        pass_commands = (
                            "G0 X35 E76 F500",
                            "G0 X25 E4 F650",
                            "G0 X15 E4 F800",
                        )
                    else:
                        pass_commands = (
                            "G0 X205 E76 F500",
                            "G0 X215 E4 F650",
                            "G0 X225 E4 F800",
                        )
                    result.extend(
                        (pass_command, None, {"spoolmanager:mmu_extra_purge"})
                        for pass_command in pass_commands
                    )
                return result
            if re.match(r"^\s*G0\s+X48\s+Z0\.05\s+F8000\b", upper):
                wipe_x = 12 if self.purge_passes % 2 == 0 else 228
                return ("G0 X%d Z0.05 F8000" % wipe_x,)
            if re.match(r"^\s*G0\s+X51\s+Z0\.2\s+F8000\b", upper):
                wipe_x = 9 if self.purge_passes % 2 == 0 else 231
                return ("G0 X%d Z0.2 F8000" % wipe_x,)

        if self.region == REGION_END:
            if re.match(r"^\s*G1\s+E-6(?:\.0+)?\s+F100\b", upper):
                return (None,)
            if re.match(r"^\s*M106\s+S256\b", upper):
                return (None,)
            if re.match(r"^\s*M104\s+S160\b", upper):
                return (None,)
            if self.unload_at_end and re.match(r"^\s*M104(?:\s+T\d+)?\s+S0(?:\.0+)?\b", upper):
                # Keep the hotend at its print target while the firmware forms
                # the tip and retracts through the extruder. Shut it down only
                # after M702 has completed successfully.
                self.deferred_hotend_off = _without_inline_comment(command)
                return (None,)
            if self.unload_at_end and not self.unload_injected and re.match(r"^\s*G4(?:\s|;|$)", upper):
                self.unload_injected = True
                # PrusaSlicer has already capped its end lift. Add clearance only
                # when the precomputed absolute target remains within machine Z.
                result = []
                if self.unload_lift_z is not None:
                    result.extend([
                        ("G90", None, {"spoolmanager:mmu_unload_lift"}),
                        (
                            "G1 Z%s F720" % _format_number(self.unload_lift_z),
                            None,
                            {"spoolmanager:mmu_unload_lift"},
                        ),
                    ])
                result.append(("M702", None, {"spoolmanager:mmu_unload"}))
                if self.deferred_hotend_off:
                    result.append((self.deferred_hotend_off, None, {"spoolmanager:mmu_unload_shutdown"}))
                result.append(_without_inline_comment(command))
                return result

        return None


def _without_inline_comment(value):
    return str(value or "").split(";", 1)[0].rstrip()


def _format_number(value):
    value = float(value)
    if value.is_integer():
        return str(int(value))
    return ("%.3f" % value).rstrip("0").rstrip(".")


def _wait_to_set_command(command):
    value = str(command or "")
    value = re.sub(r"^\s*M190\b", "M140", value, count=1, flags=re.I)
    value = re.sub(r"^\s*M109\b", "M104", value, count=1, flags=re.I)
    return value


def should_count_for_odometer(cmd, tags=None):
    command = str(cmd or "").upper()
    tag_set = set(tags or [])
    is_transport = "spoolmanager:mmu_transport" in tag_set or "SM_PURPOSE=MMU_TRANSPORT" in command
    is_select = "spoolmanager:mmu_select" in tag_set or "SM_PURPOSE=MMU_SELECT" in command
    return not is_transport and not is_select
