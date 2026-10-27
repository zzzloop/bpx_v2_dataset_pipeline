"""Server-side regression specifications; no ROS or camera needed."""
import json

from ros1_collector.numbering import inherit_take_numbers, next_take_number, reserve_take_number


def test_empty_directory_starts_at_zero(tmp_path):
    assert next_take_number(tmp_path) == 0
    assert reserve_take_number(tmp_path) == 0
    assert reserve_take_number(tmp_path) == 1


def test_missing_numbers_are_not_reused_after_restart(tmp_path):
    (tmp_path / "takes/0").mkdir(parents=True)
    (tmp_path / "takes/2").mkdir()
    assert next_take_number(tmp_path) == 3
    assert reserve_take_number(tmp_path) == 3
    # Even if the latest take directory is removed, the high-water mark survives.
    assert next_take_number(tmp_path) == 4


def test_existing_numeric_directories_and_old_episodes_are_respected(tmp_path):
    (tmp_path / "4").mkdir()
    (tmp_path / ".bpx_pending/8").mkdir(parents=True)
    (tmp_path / ".bpx_commits").mkdir()
    (tmp_path / ".bpx_commits/000010.json").write_text("{}")
    assert reserve_take_number(tmp_path) == 11


def test_counter_overrides_deleted_highest_directory(tmp_path):
    (tmp_path / ".bpx_next_take.json").write_text(json.dumps({"next": 25}))
    assert next_take_number(tmp_path) == 25


def test_four_camera_numbering_continues_old_counter_without_editing_old_dataset(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    (old / "takes/0").mkdir(parents=True)
    (old / "takes/2").mkdir()
    new.mkdir()
    before = sorted(str(path.relative_to(old)) for path in old.rglob("*"))
    inherit_take_numbers(new, old)
    assert reserve_take_number(new) == 3
    inherit_take_numbers(new, old)
    assert next_take_number(new) == 4
    assert sorted(str(path.relative_to(old)) for path in old.rglob("*")) == before


def test_startup_arrow_roundtrip_uses_real_save_dependencies():
    # Run this only in the robot/server environment, as documented.
    from ros1_collector.writer import check_save_dependencies
    check_save_dependencies()
