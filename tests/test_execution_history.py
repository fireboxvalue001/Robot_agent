import copy
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from backend import execution_history as history


def request():
    return history.ArchiveRequest(
        task_id="task_test", source_text="样品静置", kind="conditional", record_source="plan_draft",
        plan={"definition": {"entry": "hold", "nodes": [{"id": "hold", "next": "hold"}]}},
        execution_run={"status": "not_started"},
        execution_records=[{"step_id": "hold", "status": "pending", "started_at": None,
                            "finished_at": None, "key_data": {"seconds": 30}}],
        structured_result={"measurements": None})


class ExecutionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "history.sqlite3"
        self.store = history.ExecutionHistoryStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_save_restart_read_and_complete_graph_roundtrip(self):
        req = request()
        saved = self.store.save(req)
        reopened = history.ExecutionHistoryStore(self.path)
        result = reopened.get(saved["archive_id"])
        self.assertEqual(result["snapshot"], req.model_dump())
        self.assertFalse(result["execution_allowed"])
        self.assertIsNone(result["snapshot"]["execution_records"][0]["started_at"])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM step_records").fetchone()[0], 1)

    def test_duplicate_concurrent_writes_create_one_archive(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.store.save(request()), range(8)))
        self.assertEqual(len({row["archive_id"] for row in results}), 1)
        self.assertEqual(self.store.list()["total"], 1)

    def test_changed_content_is_immutable_new_snapshot_and_paginates(self):
        old = self.store.save(request())
        req = request()
        req.source_text = "第二版"
        new = self.store.save(req)
        self.assertNotEqual(old["archive_id"], new["archive_id"])
        self.assertEqual(self.store.get(old["archive_id"])["snapshot"]["source_text"], "样品静置")
        self.assertEqual(self.store.list(limit=1)["items"][0]["archive_id"], new["archive_id"])
        self.assertEqual(self.store.list(limit=1, offset=1)["items"][0]["archive_id"], old["archive_id"])
        self.assertEqual(self.store.list(task_id="no-match")["total"], 0)

    def test_simulation_source_and_timestamps_are_preserved(self):
        data = request().model_dump()
        data.update(record_source="simulation", kind="linear", execution_run={"status": "simulation_completed"})
        data["execution_records"][0].update(status="simulated_success", started_at="2026-11-04T10:00:00+08:00",
            finished_at="2026-11-04T10:00:01+08:00", duration_ms=1000)
        saved = self.store.save(history.ArchiveRequest(**data))
        self.assertEqual(self.store.get(saved["archive_id"])["snapshot"], data)

    def test_invalid_real_records_duplicate_steps_and_dates_rejected(self):
        base = request().model_dump()
        cases = []
        for status in ["running", "success", "failed"]:
            data = copy.deepcopy(base)
            data["execution_records"][0]["status"] = status
            cases.append(data)
        data = copy.deepcopy(base)
        data["execution_records"] *= 2
        cases.append(data)
        for start, end in [("bad", None), ("2026-11-04T10:00:00", None),
                           ("2026-11-04T10:00:02Z", "2026-11-04T10:00:01Z")]:
            data = copy.deepcopy(base)
            data["execution_records"][0].update(started_at=start, finished_at=end)
            cases.append(data)
        data = copy.deepcopy(base)
        data["record_source"] = "simulation"
        cases.append(data)
        data = copy.deepcopy(base)
        data["plan"]["bad"] = float("nan")
        cases.append(data)
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValidationError):
                history.ArchiveRequest(**data)

    def test_routes_unknown_id_storage_failure_and_reserved_interfaces(self):
        with patch.object(history, "store", self.store):
            with self.assertRaises(HTTPException) as error:
                history.get_archive("../../missing")
            self.assertEqual(error.exception.status_code, 404)
            saved = history.save_archive(request())
            self.assertEqual(history.get_archive(saved["archive_id"])["snapshot"]["task_id"], "task_test")
        with patch.object(history.store, "save", side_effect=sqlite3.OperationalError("private path")):
            with self.assertRaises(HTTPException) as error:
                history.save_archive(request())
            self.assertEqual(error.exception.status_code, 503)
            self.assertNotIn("private path", error.exception.detail)
        with self.assertRaises(HTTPException) as error:
            history.reserved_execution_interface()
        self.assertEqual(error.exception.status_code, 501)
        self.assertFalse(history.execution_capabilities()["device_events"])


if __name__ == "__main__":
    unittest.main()
