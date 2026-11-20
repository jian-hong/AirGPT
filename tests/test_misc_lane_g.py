"""Lane g-misc: a question keeps exactly its own files; Background tasks Clear works whatever the engine does."""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agent_store  # noqa: E402
import cortex_client  # noqa: E402
import db  # noqa: E402
import workflow_engine  # noqa: E402
from test_chat_seams import SeamsBase  # noqa: E402


class ExactTurnFiles(SeamsBase):
    def ask(self, sid, text, ids=None):
        u = db.add_message(device_ip="x", device_name="me", text=text, source="ai-chat", session_id=sid,
                           attachment_ids=ids)
        db.add_message(device_ip="x", device_name="AirGPT", text="a", source="ai", session_id=sid)
        return u

    def test_standalone_file_then_plain_question_regenerate_sends_no_file(self):
        sid = self.new_chat()
        self.file_row(sid, "alone.txt", "ZEBRA")
        u = self.ask(sid, "plain question", [])
        self.post("/api/chat/stream", {"session_id": sid, "regenerate_msg_id": u["id"]})
        self.assertEqual(self.names(self.calls[0]), [])

    def test_attached_file_regenerate_sends_it(self):
        sid = self.new_chat()
        f = self.file_row(sid, "att.txt", "ZEBRA")
        u = self.ask(sid, "about it", [f["id"]])
        self.post("/api/chat/stream", {"session_id": sid, "regenerate_msg_id": u["id"]})
        self.assertEqual(self.names(self.calls[0]), ["att.txt"])

    def test_edit_with_new_file_sends_both_and_remembers_both(self):
        sid = self.new_chat()
        f = self.file_row(sid, "att.txt", "ZEBRA")
        u = self.ask(sid, "about it", [f["id"]])
        new = self.file_row(sid, "n2.txt", "QUOKKA")
        self.post("/api/chat/stream", {"session_id": sid, "text": "edited", "replace_msg_id": u["id"],
                                       "attachment_ids": [new["id"]]})
        self.assertEqual(sorted(self.names(self.calls[0])), ["att.txt", "n2.txt"])
        q = [m for m in self.rows(sid) if m["text"] == "edited"][0]
        self.assertEqual(sorted(json.loads(q["attachment_ids"])), sorted([f["id"], new["id"]]))

    def test_old_style_question_still_gets_files_by_position(self):
        sid = self.new_chat()
        self.file_row(sid, "old.txt", "ZEBRA")
        u = self.ask(sid, "old q", None)  # saved before the column existed: no stored value
        self.assertIsNone(db.get_message(u["id"])["attachment_ids"])
        self.post("/api/chat/stream", {"session_id": sid, "regenerate_msg_id": u["id"]})
        self.assertEqual(self.names(self.calls[0]), ["old.txt"])

    def test_stream_route_records_the_attachment_ids(self):
        sid = self.new_chat()
        f = self.file_row(sid, "att.txt", "ZEBRA")
        self.post("/api/chat/stream", {"session_id": sid, "text": "hi", "attachment_ids": [f["id"]]})
        q = [m for m in self.rows(sid) if m["text"] == "hi"][0]
        self.assertEqual(json.loads(q["attachment_ids"]), [f["id"]])


class ForgedAndSequenced(SeamsBase):
    def test_other_chat_file_id_stored_on_a_question_is_refused_at_reload(self):
        mine, other = self.new_chat(), self.new_chat()
        secret = self.file_row(other, "secret.txt", "ZEBRA")
        u = db.add_message(device_ip="x", device_name="me", text="q", source="ai-chat", session_id=mine,
                           attachment_ids=[secret["id"]])
        db.add_message(device_ip="x", device_name="AirGPT", text="a", source="ai", session_id=mine)
        self.post("/api/chat/stream", {"session_id": mine, "regenerate_msg_id": u["id"]})
        self.assertEqual(self.names(self.calls[0]), [])

    def test_regenerate_ignores_attachment_ids_in_the_request(self):
        sid = self.new_chat()
        f = self.file_row(sid, "extra.txt", "ZEBRA")
        u = db.add_message(device_ip="x", device_name="me", text="q", source="ai-chat", session_id=sid, attachment_ids=[])
        db.add_message(device_ip="x", device_name="AirGPT", text="a", source="ai", session_id=sid)
        self.post("/api/chat/stream", {"session_id": sid, "regenerate_msg_id": u["id"], "attachment_ids": [f["id"]]})
        self.assertEqual(self.names(self.calls[0]), [])

    def test_two_questions_each_own_file_regenerate_last(self):
        sid = self.new_chat()
        f1 = self.file_row(sid, "one.txt", "ZEBRA")
        u1 = db.add_message(device_ip="x", device_name="me", text="q1", source="ai-chat", session_id=sid, attachment_ids=[f1["id"]])
        db.add_message(device_ip="x", device_name="AirGPT", text="a1", source="ai", session_id=sid)
        f2 = self.file_row(sid, "two.txt", "QUOKKA")
        u2 = db.add_message(device_ip="x", device_name="me", text="q2", source="ai-chat", session_id=sid, attachment_ids=[f2["id"]])
        db.add_message(device_ip="x", device_name="AirGPT", text="a2", source="ai", session_id=sid)
        self.post("/api/chat/stream", {"session_id": sid, "regenerate_msg_id": u2["id"]})
        self.assertEqual(self.names(self.calls[0]), ["two.txt"])


class ClearBackgroundTasks(unittest.TestCase):
    def setUp(self):
        self._f = workflow_engine._cleared_file()
        self._old = self._f.read_bytes() if self._f.exists() else None
        if self._f.exists():
            self._f.unlink()
        a = agent_store.create_agent("Clear agent", tools=[], kind="custom")
        self.aids = [a["id"]]
        self.rid = agent_store.create_run(a["id"], "p")["id"]

    def tearDown(self):
        if self._old is None:
            if self._f.exists():
                self._f.unlink()
        else:
            self._f.write_bytes(self._old)
        with agent_store._conn() as c:
            c.execute("UPDATE agent_runs SET status='cancelled', finished_at=1 WHERE id=?", (self.rid,))
        for aid in self.aids:  # leave no agent behind: other tests assume a clean agent list
            with agent_store._conn() as c:
                c.execute("DELETE FROM agent_runs WHERE agent_id=?", (aid,))
            agent_store.delete_agent(aid)

    def _finish(self):
        with agent_store._conn() as c:
            c.execute("UPDATE agent_runs SET status='done', finished_at=1 WHERE id=?", (self.rid,))

    def _ids(self, snap):
        return [t["id"] for t in snap["finished"]]

    def _down(self):
        return {**cortex_client._wf_down(), "running": [], "finished": []}

    def test_clear_with_engine_down_succeeds_and_hides_finished_local_runs(self):
        self._finish()
        with mock.patch.object(cortex_client, "workflows_snapshot", self._down), \
             mock.patch.object(cortex_client, "workflows_clear", lambda: cortex_client._wf_down()):
            self.assertIn(f"agent_run_{self.rid}", self._ids(workflow_engine.snapshot()))
            out = workflow_engine.clear_finished()
            self.assertTrue(out["ok"])
            snap = workflow_engine.snapshot()
        self.assertNotIn(f"agent_run_{self.rid}", self._ids(snap))
        text = str(out) + str(snap)
        for bad in ("8010", "AUTOSPAWN", "CORTEX_"):
            self.assertNotIn(bad, text)
        self.assertNotIn("hint", snap)

    def test_clear_with_engine_up_also_hides_local_runs(self):
        self._finish()
        up = {"ok": True, "running": [], "finished": [], "hint": "Start Cortex on :8010"}
        with mock.patch.object(cortex_client, "workflows_snapshot", lambda: dict(up)), \
             mock.patch.object(cortex_client, "workflows_clear", lambda: {"ok": True, "cleared": 2}):
            out = workflow_engine.clear_finished()
            snap = workflow_engine.snapshot()
        self.assertTrue(out["ok"])
        self.assertEqual(out["cleared"], 2)
        self.assertNotIn(f"agent_run_{self.rid}", self._ids(snap))
        self.assertNotIn("hint", snap)

    def test_a_running_run_is_not_hidden_by_clear(self):
        with mock.patch.object(cortex_client, "workflows_clear", lambda: cortex_client._wf_down()):
            workflow_engine.clear_finished()
        with mock.patch.object(cortex_client, "workflows_snapshot", lambda: {"ok": True, "running": [], "finished": []}):
            snap = workflow_engine.snapshot()
        self.assertTrue(any(t["id"] == f"agent_run_{self.rid}" for t in snap["running"]))

    def test_a_run_still_running_at_clear_time_shows_up_when_it_finishes(self):
        a = agent_store.create_agent("Later agent", tools=[], kind="custom")
        self.aids.append(a["id"])
        later = agent_store.create_run(a["id"], "p2")["id"]  # newer id, finishes first
        try:
            with agent_store._conn() as c:
                c.execute("UPDATE agent_runs SET status='done', finished_at=1 WHERE id=?", (later,))
            with mock.patch.object(cortex_client, "workflows_clear", lambda: cortex_client._wf_down()):
                workflow_engine.clear_finished()  # self.rid is still running
            self._finish()  # the older run ends after the clear: the user has not seen it yet
            with mock.patch.object(cortex_client, "workflows_snapshot", lambda: {"ok": True, "running": [], "finished": []}):
                snap = workflow_engine.snapshot()
            self.assertIn(f"agent_run_{self.rid}", self._ids(snap))
            self.assertNotIn(f"agent_run_{later}", self._ids(snap))
        finally:
            with agent_store._conn() as c:
                c.execute("UPDATE agent_runs SET status='cancelled', finished_at=1 WHERE id=?", (later,))

    def test_stop_error_is_plain(self):
        with mock.patch.object(cortex_client, "workflows_cancel", lambda t: cortex_client._wf_down()):
            out = workflow_engine.cancel("wf_1")
        self.assertNotIn("hint", out)
        self.assertNotIn("8010", str(out))


if __name__ == "__main__":
    unittest.main()
