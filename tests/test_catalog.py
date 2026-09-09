import pytest

from bpx_v2_dataset_pipeline.collector.catalog import TASK_PRESETS, translate_task


def test_every_task_preset_has_unique_complete_bilingual_metadata() -> None:
    assert len({item.id for item in TASK_PRESETS}) == len(TASK_PRESETS)
    assert all(item.category and item.zh and item.en for item in TASK_PRESETS)


def test_exact_preset_translation_is_high_confidence() -> None:
    result = translate_task("抓取红色方块并放入桶中。")
    assert result.english == "Pick up the red block and place it in the bucket."
    assert result.confidence == "high"


def test_supported_local_template_translation() -> None:
    result = translate_task("把蓝色方块放进盒子中")
    assert result.english == "Pick up the blue block and place it in the box."
    assert result.source == "local_rule"


def test_unknown_translation_requires_manual_input() -> None:
    result = translate_task("把实验器材整理好")
    assert result.english == ""
    assert result.source == "manual_required"


def test_empty_translation_is_rejected() -> None:
    with pytest.raises(ValueError, match="不能为空"):
        translate_task("   ")
