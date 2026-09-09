"""Offline task catalog and conservative Chinese-to-English task translation."""

from __future__ import annotations

import dataclasses
import re


@dataclasses.dataclass(frozen=True, slots=True)
class TaskPreset:
    id: str
    category: str
    zh: str
    en: str


TASK_PRESETS = (
    TaskPreset(
        "blocks_all_bucket",
        "方块抓取",
        "把桌上所有彩色方块放入桶中。",
        "Place all the colored blocks on the table into the bucket.",
    ),
    TaskPreset(
        "block_red_bucket", "方块抓取", "抓取红色方块并放入桶中。", "Pick up the red block and place it in the bucket."
    ),
    TaskPreset(
        "block_blue_bucket",
        "方块抓取",
        "抓取蓝色方块并放入桶中。",
        "Pick up the blue block and place it in the bucket.",
    ),
    TaskPreset(
        "block_green_bucket",
        "方块抓取",
        "抓取绿色方块并放入桶中。",
        "Pick up the green block and place it in the bucket.",
    ),
    TaskPreset(
        "block_orange_bucket",
        "方块抓取",
        "抓取橙色方块并放入桶中。",
        "Pick up the orange block and place it in the bucket.",
    ),
    TaskPreset(
        "block_purple_bucket",
        "方块抓取",
        "抓取紫色方块并放入桶中。",
        "Pick up the purple block and place it in the bucket.",
    ),
    TaskPreset("bottle_bucket", "常见物体", "抓取瓶子并放入桶中。", "Pick up the bottle and place it in the bucket."),
    TaskPreset(
        "mouse_bucket", "常见物体", "抓取鼠标并放入桶中。", "Pick up the computer mouse and place it in the bucket."
    ),
    TaskPreset(
        "shuttlecock_bucket",
        "常见物体",
        "抓取羽毛球并放入桶中。",
        "Pick up the shuttlecock and place it in the bucket.",
    ),
    TaskPreset(
        "stack_red_blue", "堆叠", "把红色方块叠放在蓝色方块上。", "Stack the red block on top of the blue block."
    ),
    TaskPreset("drawer_open", "开合操作", "拉开抽屉。", "Open the drawer."),
    TaskPreset("drawer_close", "开合操作", "推上抽屉。", "Close the drawer."),
    TaskPreset("peg_insert", "精密操作", "把圆柱插入对应的圆孔。", "Insert the cylinder into the matching round hole."),
    TaskPreset(
        "object_handover",
        "双臂操作",
        "把物体从左手传递到右手。",
        "Transfer the object from the left hand to the right hand.",
    ),
)

DEFAULT_OPERATORS = tuple(f"operator_{index:02d}" for index in range(1, 9))
DEFAULT_LAYOUTS = (
    "layout_fixed_01",
    "layout_fixed_02",
    "layout_random_easy_01",
    "layout_random_medium_01",
    "layout_random_hard_01",
    "layout_distractors_01",
)


@dataclasses.dataclass(frozen=True, slots=True)
class TranslationResult:
    english: str
    source: str
    confidence: str


def _normalize_chinese(text: str) -> str:
    return re.sub(r"[\s\uFF0C\u3002\uFF01\uFF1F\u3001,.!?]", "", text.strip())


_EXACT_TRANSLATIONS = {_normalize_chinese(item.zh): item.en for item in TASK_PRESETS}
_OBJECTS = {
    "红色方块": "the red block",
    "蓝色方块": "the blue block",
    "绿色方块": "the green block",
    "橙色方块": "the orange block",
    "紫色方块": "the purple block",
    "方块": "the block",
    "瓶子": "the bottle",
    "鼠标": "the computer mouse",
    "羽毛球": "the shuttlecock",
}
_TARGETS = {
    "桶中": "the bucket",
    "桶里": "the bucket",
    "盒中": "the box",
    "盒子中": "the box",
    "盒里": "the box",
    "托盘中": "the tray",
    "托盘里": "the tray",
}
_PICK_AND_PLACE = re.compile(
    rf"^(?:把|将)?(?:抓取|抓起|拿起|拾取)?(?P<object>{'|'.join(_OBJECTS)})(?:并|然后|再|将其)*"
    rf"(?:放入|放进|放到)(?P<target>{'|'.join(_TARGETS)})$"
)


def translate_task(text: str) -> TranslationResult:
    """Translate catalog tasks and one deliberately narrow pick-and-place template."""
    normalized = _normalize_chinese(text)
    if not normalized:
        raise ValueError("中文指令不能为空")
    if english := _EXACT_TRANSLATIONS.get(normalized):
        return TranslationResult(english, "preset", "high")
    if match := _PICK_AND_PLACE.fullmatch(normalized):
        object_name = _OBJECTS[match.group("object")]
        target_name = _TARGETS[match.group("target")]
        return TranslationResult(f"Pick up {object_name} and place it in {target_name}.", "local_rule", "medium")
    return TranslationResult("", "manual_required", "none")
