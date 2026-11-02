#!/usr/bin/env python3
"""Offline tests for tunarr_relink.py's custom-show repair (Tunarr 2026.x slot path).

The live dry run on 2026-11-02 found no resolvable dead films on the slot channels,
so the write path never ran against real data. These tests drive the REAL module
against an in-memory Tunarr: tun() is replaced, nothing touches the network.

Usage:  python3 tools/media/test_tunarr_relink.py
"""
import importlib.util, os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SHOW = "5db2bab2-7612-5d08-83cd-87b4d8c474e3"
SWAP = {"dead-a": {"id": "live-a", "duration": 6000, "old": "Titicut Follies", "new_key": "901"}}


def load_relink():
    spec = importlib.util.spec_from_file_location("tunarr_relink", os.path.join(HERE, "tunarr_relink.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeTunarr:
    """Holds one custom show and one channel; records every write."""

    def __init__(self, show_ids, keep_writes=True):
        self.show = [{"id": u, "index": i, "duration": 1000} for i, u in enumerate(show_ids)]
        self.channel_programs = {u: {"type": "content"} for u in show_ids}
        self.keep_writes = keep_writes
        self.writes = []

    def put(self, path, body):
        assert path == "/api/custom-shows/" + SHOW, path
        self.writes.append(("show", body))
        if self.keep_writes:
            self.show = [{"id": p["id"], "index": i, "duration": p["duration"]} for i, p in enumerate(body["programs"])]

    def __call__(self, path, body=None):
        if path == "/api/custom-shows/" + SHOW + "/programs":
            return list(reversed(self.show))           # out of order on purpose: index decides
        if path == "/api/channels/ch27/programming" and body is not None:
            self.writes.append(("channel", body))
            if self.keep_writes:
                self.channel_programs = {u: {"type": "content"} for u in body["programs"]}
            return {}
        if path == "/api/channels/ch27/programming":
            return {"programs": self.channel_programs}
        raise AssertionError("unexpected call " + path)


def schedule(*slot_types):
    slots = [{"type": t, "customShowId": SHOW} if t == "custom-show" else {"type": t} for t in slot_types]
    return {"type": "random", "slots": slots}


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.relink = load_relink()
        self.relink.REPAIRED_SHOWS.clear()
        self.relink.BACKUP = tempfile.mkdtemp()
        self.relink.log = lambda message: None
        self.channel = {"id": "ch27", "number": 27, "name": "Frederick Wiseman"}

    def use(self, fake, apply):
        self.relink.tun = fake
        self.relink.tun_put = fake.put
        self.relink.APPLY = apply
        return fake

    def test_dry_run_reports_without_writing(self):
        fake = self.use(FakeTunarr(["keep-1", "dead-a", "keep-2"]), apply=False)
        self.assertEqual(self.relink.repair_show(SHOW, SWAP, "t"), ["keep-1", "live-a", "keep-2"])
        self.assertEqual(fake.writes, [])

    def test_apply_swaps_in_place_with_new_duration(self):
        fake = self.use(FakeTunarr(["keep-1", "dead-a", "keep-2"]), apply=True)
        self.assertEqual(self.relink.repair_show(SHOW, SWAP, "t"), ["keep-1", "live-a", "keep-2"])
        kind, body = fake.writes[0]
        self.assertEqual(kind, "show")
        self.assertFalse(body["enableSync"])
        self.assertEqual([(p["id"], p["duration"]) for p in body["programs"]],
                         [("keep-1", 1000), ("live-a", 6000), ("keep-2", 1000)])

    def test_live_twin_already_present_aborts_without_writing(self):
        fake = self.use(FakeTunarr(["dead-a", "live-a"]), apply=True)
        self.assertIsNone(self.relink.repair_show(SHOW, SWAP, "t"))
        self.assertEqual(fake.writes, [])

    def test_show_that_does_not_take_the_write_is_a_failure(self):
        self.use(FakeTunarr(["dead-a"], keep_writes=False), apply=True)
        self.assertIsNone(self.relink.repair_show(SHOW, SWAP, "t"))

    def test_channel_lineup_rebuilt_from_repaired_show(self):
        fake = self.use(FakeTunarr(["keep-1", "dead-a"]), apply=True)
        result = self.relink.relink_slots(self.channel, {"programs": fake.channel_programs}, schedule("custom-show", "flex"), SWAP)
        self.assertEqual(result, (1, 0))
        kind, body = fake.writes[-1]
        self.assertEqual(kind, "channel")
        self.assertEqual(body["programs"], ["keep-1", "live-a"])
        self.assertEqual(body["schedule"]["type"], "random")

    def test_dry_run_counts_dead_films_without_writing(self):
        fake = self.use(FakeTunarr(["keep-1", "dead-a"]), apply=False)
        result = self.relink.relink_slots(self.channel, {"programs": fake.channel_programs}, schedule("custom-show"), SWAP)
        self.assertEqual(result, (1, 0))
        self.assertEqual(fake.writes, [])

    def test_show_without_dead_films_is_returned_unchanged(self):
        fake = self.use(FakeTunarr(["keep-1", "keep-2"]), apply=True)
        self.assertEqual(self.relink.repair_show(SHOW, SWAP, "t"), ["keep-1", "keep-2"])
        self.assertEqual(fake.writes, [])

    def test_failed_show_blocks_the_lineup_rebuild(self):
        fake = self.use(FakeTunarr(["dead-a", "live-a"]), apply=True)
        result = self.relink.relink_slots(self.channel, {"programs": fake.channel_programs}, schedule("custom-show"), SWAP)
        self.assertEqual(result, (0, 1))
        self.assertEqual(fake.writes, [])

    def test_channel_without_dead_films_is_untouched(self):
        fake = self.use(FakeTunarr(["keep-1"]), apply=True)
        self.assertEqual(self.relink.relink_slots(self.channel, {"programs": fake.channel_programs}, schedule("custom-show"), SWAP), (0, 0))
        self.assertEqual(fake.writes, [])

    def test_unhandled_slot_type_and_schedule_type_are_skipped(self):
        fake = self.use(FakeTunarr(["dead-a"]), apply=True)
        programs = {"programs": fake.channel_programs}
        self.assertEqual(self.relink.relink_slots(self.channel, programs, schedule("smart-collection"), SWAP), (0, 0))
        self.assertEqual(self.relink.relink_slots(self.channel, programs, {"type": "time", "slots": []}, SWAP), (0, 0))
        self.assertEqual(fake.writes, [])

    def test_lineup_still_holding_dead_film_is_a_failure(self):
        fake = self.use(FakeTunarr(["dead-a"]), apply=True)
        original_call = fake.__call__

        def channel_ignores_write(path, body=None):
            if path == "/api/channels/ch27/programming" and body is not None:
                fake.writes.append(("channel", body))
                return {}
            return original_call(path, body)

        self.relink.tun = channel_ignores_write
        self.assertEqual(self.relink.relink_slots(self.channel, {"programs": dict(fake.channel_programs)}, schedule("custom-show"), SWAP), (1, 1))


class TunPutTests(unittest.TestCase):
    def test_sends_json_body_with_put(self):
        relink = load_relink()
        sent = []

        class Response:
            def read(self):
                return b""

        with mock.patch.object(relink.urllib.request, "urlopen", lambda request, timeout: sent.append(request) or Response()):
            relink.tun_put("/api/custom-shows/x", {"programs": []})
        self.assertEqual((sent[0].get_method(), sent[0].full_url, sent[0].data),
                         ("PUT", relink.TUNARR + "/api/custom-shows/x", b'{"programs": []}'))


if __name__ == "__main__":
    sys.exit(unittest.main())
