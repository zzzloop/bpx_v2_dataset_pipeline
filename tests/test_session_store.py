import pathlib
import tempfile
import unittest

from bpx_v2_dataset_pipeline.models import AttemptMetadata, AttemptStatus
from bpx_v2_dataset_pipeline.session_store import SessionStore


def metadata() -> AttemptMetadata:
    return AttemptMetadata(
        session_id="session-a",
        task_en="Pick up the red block.",
        operator_id="operator-1",
        layout_id="layout-1",
        embodiment="gripper",
    )


class SessionStoreTest(unittest.TestCase):
    def test_failed_attempt_id_is_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(pathlib.Path(directory) / "collector.sqlite3")
            first = store.begin_attempt(metadata())
            store.finish_attempt(first, AttemptStatus.FAILURE)
            second = store.begin_attempt(metadata())
            self.assertEqual(second, first + 1)

    def test_restart_marks_recording_attempt_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(pathlib.Path(directory) / "collector.sqlite3")
            attempt_id = store.begin_attempt(metadata())
            self.assertEqual(store.recover_interrupted(), 1)
            self.assertEqual(store.get_attempt(attempt_id)["status"], AttemptStatus.INTERRUPTED)

    def test_failure_reason_is_stored_only_for_failed_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(pathlib.Path(directory) / "collector.sqlite3")
            successful = store.begin_attempt(metadata())
            store.finish_attempt(successful, AttemptStatus.SUCCESS, failure_reason="must not persist")
            self.assertEqual(store.get_attempt(successful)["failure_reason"], "")

            failed = store.begin_attempt(metadata())
            store.finish_attempt(failed, AttemptStatus.FAILURE, failure_reason="grasp slipped")
            self.assertEqual(store.get_attempt(failed)["failure_reason"], "grasp slipped")


if __name__ == "__main__":
    unittest.main()
