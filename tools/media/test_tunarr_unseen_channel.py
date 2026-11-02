#!/usr/bin/env python3
"""Offline tests for tunarr_unseen_channel.custom_show_for(). tun() is replaced; no network.

Usage:  python3 tools/media/test_tunarr_unseen_channel.py
"""
import importlib.util, os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAMS = [{"type": "content", "id": "film-1", "duration": 6000}]


def load_script():
    spec = importlib.util.spec_from_file_location("tunarr_unseen_channel", os.path.join(HERE, "tunarr_unseen_channel.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CustomShowForTests(unittest.TestCase):
    def setUp(self):
        self.script = load_script()
        self.calls = []

    def fake_tun(self, existing):
        def tun(path, method="GET", body=None, base=None, timeout=180):
            self.calls.append((method, path, body, base))
            if method == "GET":
                return existing
            return {"id": "new-show"} if method == "POST" else {}
        self.script.tun = tun

    def test_existing_show_is_refilled_in_place(self):
        self.fake_tun([{"name": "Unseen — Both Movies", "id": "show-40"}, {"name": "Other", "id": "x"}])
        self.assertEqual(self.script.custom_show_for("Unseen — Both Movies", PROGRAMS, "http://t"), "show-40")
        self.assertEqual(self.calls[-1], ("PUT", "/api/custom-shows/show-40",
                                          {"programs": PROGRAMS, "enableSync": False}, "http://t"))

    def test_missing_show_is_created_without_sync(self):
        self.fake_tun([])
        self.assertEqual(self.script.custom_show_for("Unseen — Zach Movies", PROGRAMS, "http://t"), "new-show")
        method, path, body, _ = self.calls[-1]
        self.assertEqual((method, path, body["name"], body["programs"], body["syncExternalPlaylistId"]),
                         ("POST", "/api/custom-shows", "Unseen — Zach Movies", PROGRAMS, None))


if __name__ == "__main__":
    sys.exit(unittest.main())
