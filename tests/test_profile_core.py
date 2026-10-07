import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages"))

from profile_core import ProfileService, ProfileStore, now_iso  # noqa: E402


def svc(tmp):
    return ProfileService(ProfileStore(os.path.join(tmp, "profile.db")), actor="test")


class ProfileCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="contextcanon-profile-")
        self.service = svc(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_upsert_and_read(self):
        self.service.upsert_fact("s1", "timezone", "Europe/Lisbon", actor="test")
        fact = self.service.get_fact("s1", "timezone")
        self.assertEqual(fact["value"], "Europe/Lisbon")
        self.assertEqual(fact["status"], "active")
        self.assertEqual(fact["revision"], 1)

    def test_idempotent_restatement(self):
        self.service.upsert_fact("s1", "k", "v", actor="test")
        result = self.service.upsert_fact("s1", "k", "v", actor="test")
        self.assertEqual(result["action"], "unchanged")
        self.assertEqual(len(self.service.history("s1", "k")), 1)

    def test_supersede_keeps_old_revision(self):
        self.service.upsert_fact("s1", "editor", "vscode", actor="test")
        result = self.service.upsert_fact("s1", "editor", "zed", actor="test")
        self.assertEqual(result["action"], "superseded")
        history = self.service.history("s1", "editor")
        self.assertEqual([f["value"] for f in history], ["vscode", "zed"])
        self.assertEqual(history[0]["status"], "superseded")
        self.assertEqual(history[1]["status"], "active")
        self.assertEqual(history[0]["superseded_by"], history[1]["fact_id"])

    def test_rejected_conflict_does_not_overwrite(self):
        self.service.upsert_fact("s1", "timezone", "Europe/Lisbon", actor="test")
        result = self.service.upsert_fact("s1", "timezone", "America/New_York",
                                          on_conflict="reject", actor="test")
        self.assertEqual(result["action"], "rejected")
        active = self.service.get_fact("s1", "timezone")
        self.assertEqual(active["value"], "Europe/Lisbon")
        all_facts = self.service.store.all_facts()
        rejected = [f for f in all_facts if f["status"] == "rejected"]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["value"], "America/New_York")

    def test_keep_policy(self):
        self.service.upsert_fact("s1", "k", "old", actor="test")
        result = self.service.upsert_fact("s1", "k", "new", on_conflict="keep", actor="test")
        self.assertEqual(result["action"], "kept")
        self.assertEqual(self.service.get_fact("s1", "k")["value"], "old")

    def test_temporal_as_of(self):
        self.service.upsert_fact("s1", "editor", "vscode", valid_from="2020-01-01T00:00:00Z",
                                 actor="test", nonce="a")
        self.service.upsert_fact("s1", "editor", "zed", valid_from="2025-01-01T00:00:00Z",
                                 actor="test", nonce="b")
        past = self.service.as_of("s1", "2022-01-01T00:00:00Z")
        values = {f["key"]: f["value"] for f in past}
        self.assertEqual(values["editor"], "vscode")
        present = self.service.as_of("s1", "2030-01-01T00:00:00Z")
        self.assertEqual({f["key"]: f["value"] for f in present}["editor"], "zed")

    def test_scheduled_fact_window(self):
        self.service.upsert_fact("s1", "event", "conference", durability="scheduled",
                                 valid_from="2030-01-01T00:00:00Z",
                                 valid_until="2030-01-03T00:00:00Z", actor="test")
        self.assertEqual(len(self.service.as_of("s1", "2029-01-01T00:00:00Z")), 0)
        self.assertEqual(len(self.service.as_of("s1", "2030-01-02T00:00:00Z")), 1)
        self.assertEqual(len(self.service.as_of("s1", "2031-01-01T00:00:00Z")), 0)

    def test_expired_is_auditable_not_deleted(self):
        self.service.upsert_fact("s1", "pass", "winter", durability="temporary",
                                 valid_from="2020-01-01T00:00:00Z",
                                 valid_until="2020-06-01T00:00:00Z", actor="test")
        expired = self.service.expire_due_facts("2021-01-01T00:00:00Z")
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0]["status"], "expired")
        self.assertIsNone(self.service.get_fact("s1", "pass"))
        found = self.service.get_fact("s1", "pass", include_inactive=True)
        self.assertIsNotNone(found)
        self.assertEqual(found["status"], "expired")

    def test_provenance_recorded(self):
        self.service.upsert_fact("s1", "k", "v", actor="test",
                                 provenance={"source": "inferred", "confidence": 0.4,
                                             "ref": "some-doc", "method": "guessed"})
        fact = self.service.get_fact("s1", "k")
        self.assertEqual(fact["provenance"]["source"], "inferred")
        self.assertAlmostEqual(fact["provenance"]["confidence"], 0.4)

    def test_sensitivity_levels(self):
        for level in ("public", "personal", "sensitive", "restricted"):
            self.service.upsert_fact("s1", "k_" + level, "v", sensitivity=level, actor="test")
        facts = self.service.list_facts("s1")
        self.assertEqual({f["key"]: f["sensitivity"] for f in facts}["k_restricted"], "restricted")

    def test_audit_trail(self):
        self.service.upsert_fact("s1", "editor", "vscode", actor="test")
        self.service.upsert_fact("s1", "editor", "zed", actor="test")
        events = self.service.audit("s1")
        kinds = [e["event_type"] for e in events]
        self.assertIn("fact.created", kinds)
        self.assertIn("fact.superseded", kinds)

    def test_reject_conflict_tool_path(self):
        self.service.upsert_fact("s1", "k", "v", actor="test")
        fact = self.service.get_fact("s1", "k")
        result = self.service.reject_conflict(fact["fact_id"], reason="outdated")
        self.assertEqual(result["fact"]["status"], "rejected")

    def test_lifecycle_report(self):
        self.service.upsert_fact("s1", "a", 1, durability="durable", actor="test")
        self.service.upsert_fact("s1", "b", 2, durability="temporary", actor="test")
        self.service.upsert_fact("s1", "c", 3, durability="scheduled", actor="test")
        report = self.service.lifecycle_report("s1")
        self.assertEqual(report["total"], 3)
        self.assertEqual(sorted(report["by_durability"]), ["durable", "scheduled", "temporary"])

    # ---------------------------------------------- MAJOR-1 temporal currency

    def test_future_revision_is_not_current(self):
        """A revision whose valid_from is in the future must not be current."""
        self.service.upsert_fact("s1", "city", "Porto",
                                 valid_from="2020-01-01T00:00:00Z", actor="test",
                                 provenance={"source": "user-stated"})
        self.service.upsert_fact("s1", "city", "Tokyo",
                                 valid_from="2999-01-01T00:00:00Z", actor="test",
                                 nonce="sched-tokyo", provenance={"source": "document"})
        # what is true now is still the old value; the scheduled one has not arrived
        self.assertEqual(self.service.get_fact("s1", "city")["value"], "Porto")
        # and it agrees with a temporal read at "now"
        now_view = {f["key"]: f["value"] for f in self.service.as_of("s1", now_iso())}
        self.assertEqual(now_view["city"], "Porto")

    def test_current_read_matches_as_of_now(self):
        """The current read and as_of(now) must resolve identically."""
        self.service.upsert_fact("s1", "a", "present", actor="test")
        self.service.upsert_fact("s1", "b", "future",
                                 valid_from="2999-01-01T00:00:00Z", actor="test", nonce="nb")
        self.service.upsert_fact("s1", "c", "gone",
                                 valid_from="2020-01-01T00:00:00Z",
                                 valid_until="2020-06-01T00:00:00Z", actor="test", nonce="nc")
        current = {f["key"]: f["value"] for f in self.service.list_facts("s1")}
        as_of_now = {f["key"]: f["value"] for f in self.service.as_of("s1", now_iso())}
        self.assertEqual(current, as_of_now)
        self.assertEqual(current, {"a": "present"})
        self.assertIsNone(self.service.get_fact("s1", "b"))

    def test_scheduled_revision_does_not_hide_current_value(self):
        """The future revision must not make the old current fact disappear."""
        self.service.upsert_fact("s1", "city", "Porto",
                                 valid_from="2020-01-01T00:00:00Z", actor="test", nonce="p")
        self.service.upsert_fact("s1", "city", "Tokyo",
                                 valid_from="2999-01-01T00:00:00Z", actor="test", nonce="t")
        self.assertEqual(self.service.get_fact("s1", "city")["value"], "Porto")
        # once the window arrives, the new revision becomes current
        later = {f["key"]: f["value"] for f in self.service.as_of("s1", "2999-06-01T00:00:00Z")}
        self.assertEqual(later["city"], "Tokyo")

    def test_supersede_chain_and_provenance_remain_auditable(self):
        self.service.upsert_fact("s1", "city", "Porto",
                                 valid_from="2020-01-01T00:00:00Z", actor="test",
                                 provenance={"source": "user-stated", "confidence": 1.0})
        self.service.upsert_fact("s1", "city", "Tokyo",
                                 valid_from="2999-01-01T00:00:00Z", actor="test", nonce="t",
                                 provenance={"source": "document", "confidence": 0.85})
        history = self.service.history("s1", "city")
        self.assertEqual([f["value"] for f in history], ["Porto", "Tokyo"])
        self.assertEqual(history[0]["superseded_by"], history[1]["fact_id"])
        self.assertEqual(history[0]["provenance"]["source"], "user-stated")
        self.assertEqual(history[1]["provenance"]["source"], "document")
        kinds = [e["event_type"] for e in self.service.audit("s1")]
        self.assertIn("fact.created", kinds)
        self.assertIn("fact.superseded", kinds)

    # ------------------------------------------- MINOR-A / MINOR-B regressions

    def test_fact_id_collision_on_within_second_flip_flop(self):
        """A -> B -> A inside one second used to raise a UNIQUE constraint error."""
        first = self.service.upsert_fact("s1", "k", "A", actor="test")
        second = self.service.upsert_fact("s1", "k", "B", actor="test")
        third = self.service.upsert_fact("s1", "k", "A", actor="test")
        ids = {first["fact"]["fact_id"], second["fact"]["fact_id"], third["fact"]["fact_id"]}
        self.assertEqual(len(ids), 3, "each write must get its own fact_id")
        self.assertEqual(self.service.get_fact("s1", "k")["value"], "A")
        self.assertEqual([f["value"] for f in self.service.history("s1", "k")], ["A", "B", "A"])

    def test_type_change_is_a_new_revision(self):
        """1 vs "1" and True vs "True" are different values, not 'unchanged'."""
        self.service.upsert_fact("s1", "n", 1, actor="test")
        result = self.service.upsert_fact("s1", "n", "1", actor="test")
        self.assertNotEqual(result["action"], "unchanged")
        self.assertEqual(self.service.get_fact("s1", "n")["value"], "1")

        self.service.upsert_fact("s1", "flag", True, actor="test")
        result = self.service.upsert_fact("s1", "flag", "True", actor="test")
        self.assertNotEqual(result["action"], "unchanged")
        self.assertEqual(self.service.get_fact("s1", "flag")["value"], "True")

    def test_same_type_same_value_is_still_unchanged(self):
        self.service.upsert_fact("s1", "n", 40, actor="test")
        self.assertEqual(self.service.upsert_fact("s1", "n", 40, actor="test")["action"], "unchanged")


if __name__ == "__main__":
    unittest.main()
