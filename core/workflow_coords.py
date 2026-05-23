"""工作流与全局按钮参考坐标（与 config/config.yaml 用户校准值同步）"""
from __future__ import annotations

from typing import Any, Dict, List

WORKFLOW_COUNT = 6
SLOT_COUNT = 6
STEP2_SLOT_INDEX = 5
STEP3_SLOT_INDEX = 5

REFERENCE_GLOBAL_BUTTONS: Dict[str, Dict[str, int]] = {
    "back": {"x": 352, "y": 764},
    "record": {"x": 478, "y": 771},
    "listen": {"x": 561, "y": 766},
    "replay": {"x": 733, "y": 764},
    "forward": {"x": 798, "y": 767},
}

REFERENCE_STEP1_SLOTS: List[Dict[str, int]] = [
    {"x": 418, "y": 330},
    {"x": 765, "y": 333},
    {"x": 449, "y": 434},
    {"x": 764, "y": 434},
    {"x": 428, "y": 522},
    {"x": 767, "y": 521},
]

REFERENCE_STEP2_SHARED: List[Dict[str, int]] = [
    {"x": 456, "y": 282},
    {"x": 456, "y": 356},
    {"x": 471, "y": 442},
    {"x": 474, "y": 510},
    {"x": 464, "y": 596},
    {"x": 454, "y": 664},
]

REFERENCE_STEP3_SHARED: List[Dict[str, int]] = [
    {"x": 777, "y": 283},
    {"x": 766, "y": 359},
    {"x": 771, "y": 430},
    {"x": 769, "y": 507},
    {"x": 767, "y": 592},
    {"x": 758, "y": 672},
]


def use_reference_defaults(config: Any) -> bool:
    coords = config.get("coords")
    if isinstance(coords, dict) and "use_reference_defaults" in coords:
        return bool(coords.get("use_reference_defaults"))
    return False


def mark_coords_user_calibrated(config: Any) -> None:
    c = config.config.setdefault("coords", {})
    if isinstance(c, dict):
        c["use_reference_defaults"] = False


def _is_zero(pt: Dict[str, int]) -> bool:
    return int(pt.get("x", 0)) == 0 and int(pt.get("y", 0)) == 0


def ensure_reference_coord_defaults(config: Any) -> bool:
    changed = False
    force = use_reference_defaults(config)

    gb = config.config.setdefault("global_buttons", {})
    for key, ref in REFERENCE_GLOBAL_BUTTONS.items():
        cur = gb.get(key) if isinstance(gb.get(key), dict) else {}
        if force or not cur or _is_zero(cur):
            gb[key] = dict(ref)
            changed = True

    wf = config.config.setdefault("workflows", {})
    for name, ref_list in (
        ("step1_slots", REFERENCE_STEP1_SLOTS),
        ("step2_shared", REFERENCE_STEP2_SHARED),
        ("step3_shared", REFERENCE_STEP3_SHARED),
    ):
        slots = wf.setdefault(name, [])
        while len(slots) < SLOT_COUNT:
            slots.append({"x": 0, "y": 0})
        for i, ref in enumerate(ref_list):
            cur = slots[i] if i < len(slots) else {}
            if force or not cur or _is_zero(cur):
                slots[i] = dict(ref)
                changed = True
        wf[name] = slots[:SLOT_COUNT]

    return changed


def get_step1_coord(config: Any, wf_index: int) -> Dict[str, int]:
    slots = config.get("workflows.step1_slots") or REFERENCE_STEP1_SLOTS
    return dict(slots[wf_index - 1])


def get_step2_coord(config: Any, slot_index: int = STEP2_SLOT_INDEX) -> Dict[str, int]:
    slots = config.get("workflows.step2_shared") or REFERENCE_STEP2_SHARED
    return dict(slots[slot_index])


def get_step3_coord(config: Any, slot_index: int = STEP3_SLOT_INDEX) -> Dict[str, int]:
    slots = config.get("workflows.step3_shared") or REFERENCE_STEP3_SHARED
    return dict(slots[slot_index])


def get_global_button(config: Any, name: str) -> Dict[str, int]:
    buttons = config.get("global_buttons") or REFERENCE_GLOBAL_BUTTONS
    return dict(buttons.get(name, REFERENCE_GLOBAL_BUTTONS.get(name, {"x": 0, "y": 0})))
