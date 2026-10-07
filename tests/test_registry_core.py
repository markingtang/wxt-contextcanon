import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages"))

from registry_core import RegistryService, RegistryStore  # noqa: E402


class RegistryCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="contextcanon-registry-")
        self.service = RegistryService(
            RegistryStore(os.path.join(self.tmp, "registry.db")),
            device_id="device-a",
            device_role="primary",
        )
        self.service.ensure_device()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_device_identity(self):
        devices = self.service.list_devices()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["device_id"], "device-a")

    def test_task_intent_open_then_closed(self):
        self.service.begin_task("t1", "reorganise", ["a.md"])
        self.assertIn("t1", self.service.open_tasks())
        self.service.end_task("t1", "ok", ["a.md"])
        self.assertNotIn("t1", self.service.open_tasks())

    def test_outbox_drain_and_idempotency(self):
        self.service.store.enqueue("ob-1", "device-b", "file.upsert",
                                   {"object_key": "a.md", "checksum": "c1"}, "2026-01-01T00:00:00Z")
        first = self.service.drain_outbox()
        self.assertEqual(first["applied"], 1)
        rows = self.service.query("a.md", "device-b")
        self.assertEqual(rows[0]["state"]["status"], "present")

        # Deliver the same work again: no double apply.
        self.service.store.mark_outbox("ob-1", "pending", "", "2026-01-01T00:00:00Z")
        second = self.service.drain_outbox()
        self.assertEqual(second["applied"], 0)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(self.service.query("a.md", "device-b")[0]["version"], 1)

    def test_rebuild_is_a_projection(self):
        for key in ("a.md", "b.md", "c.md"):
            self.service.append_event("file.upsert", {"object_key": key, "checksum": "c"})
        self.service.apply_all()
        before = self.service.query()
        result = self.service.rebuild_shared_index()
        self.assertFalse(result["last_good_used"])
        after = self.service.query()
        self.assertEqual(len(before), len(after))

    def test_last_good_behaviour_on_failed_rebuild(self):
        self.service.append_event("file.upsert", {"object_key": "a.md", "checksum": "c"})
        self.service.apply_all()
        good = self.service.query()

        original = self.service.store.all_events
        self.service.store.all_events = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            result = self.service.rebuild_shared_index()
        finally:
            self.service.store.all_events = original
        self.assertTrue(result["last_good_used"])
        self.assertEqual(len(self.service.query()), len(good))

    def test_offline_recovery_converges(self):
        self.service.append_event("file.upsert", {"object_key": "a.md", "checksum": "c1"})
        self.service.apply_all()
        for index, key in enumerate(("b.md", "c.md")):
            self.service.store.enqueue("ob-%d" % index, "device-b", "file.upsert",
                                       {"object_key": key, "checksum": "c2"}, "2026-01-01T00:00:00Z")
        result = self.service.offline_recovery()
        self.assertTrue(result["converged"])
        self.assertEqual(self.service.status()["pending_outbox"], 0)
        self.assertEqual(len(self.service.query()), 3)

    def test_manifest_checksum(self):
        result = self.service.record_manifest("scope", [{"object_key": "a.md"}, {"object_key": "b.md"}])
        self.assertEqual(result["entry_count"], 2)
        manifests = self.service.list_manifests()
        self.assertEqual(manifests[0]["checksum"], result["checksum"])

    def test_delete_event(self):
        self.service.append_event("file.upsert", {"object_key": "a.md", "checksum": "c"})
        self.service.apply_all()
        self.service.append_event("file.delete", {"object_key": "a.md"})
        self.service.apply_all()
        self.assertEqual(self.service.query("a.md")[0]["state"]["status"], "deleted")

    def test_status_shape(self):
        status = self.service.status()
        for key in ("device_id", "event_count", "pending_outbox", "index_rows", "open_tasks"):
            self.assertIn(key, status)

    # ------------------------------------------------- MAJOR-2 / §4 registry

    def test_recover_leaves_no_phantom_open_tasks(self):
        """begin+end through recovery must not resurrect a closed task."""
        for index in range(16):
            self.service.begin_task("task-%d" % index, "work")
            self.service.end_task("task-%d" % index, "ok")
        self.service.offline_recovery()
        self.assertEqual(self.service.open_tasks(), [])

    def test_begin_end_then_drain_does_not_duplicate_events(self):
        self.service.begin_task("t1", "work")
        self.service.end_task("t1", "ok")
        self.assertEqual(len(self.service.store.all_events()), 2)
        self.service.drain_outbox()
        self.assertEqual(len(self.service.store.all_events()), 2, "drain must not add a second copy")
        self.assertEqual(self.service.open_tasks(), [])

    def test_begin_without_end_stays_open_after_drain(self):
        self.service.begin_task("t-open", "work")
        self.service.drain_outbox()
        self.assertIn("t-open", self.service.open_tasks())

    def test_offline_recovery_twice_is_idempotent(self):
        self.service.begin_task("t1", "work")
        self.service.end_task("t1", "ok")
        self.service.offline_recovery()
        second = self.service.offline_recovery()
        self.assertEqual(second["drained"]["applied"], 0)
        self.assertEqual(self.service.open_tasks(), [])
        self.assertEqual(len(self.service.store.all_events()), 2)

    def test_file_event_without_object_key_fails_closed(self):
        event = self.service.append_event("file.upsert", {})
        applied = self.service.apply_all()
        self.assertEqual(applied, 0)
        self.assertFalse(self.service.store.already_applied(event["event_id"]))
        self.assertEqual(self.service.query(), [])

    def test_identical_events_in_same_second_get_distinct_ids(self):
        first = self.service.append_event("file.upsert", {"object_key": "x", "checksum": "c"})
        second = self.service.append_event("file.upsert", {"object_key": "x", "checksum": "c"})
        self.assertNotEqual(first["event_id"], second["event_id"])
        self.assertEqual(len(self.service.store.all_events()), 2)


if __name__ == "__main__":
    unittest.main()
