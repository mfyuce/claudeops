"""Güvenilmeyen uzak `/api/status` biçimi (TBD#372): bozuk satır/alan yerel birleştirmeyi ve poller turunu düşürmez.
Gerçek ağ/uzak host YOK; host listesi, ayarlar ve HTTP yanıtı sahte."""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from claudeops.commands import web_hosts  # noqa: E402


class MergeStatusBadFieldsTest(unittest.TestCase):
    def merge(self, remote_rows, sort="name"):
        cached = {"ok": True, "error": None, "sessions": [dict(r) for r in remote_rows],
                  "closed": [dict(r) for r in remote_rows], "retired": [dict(r) for r in remote_rows],
                  "cli_list": [], "cli_options": {}, "dups": []}
        local = {"name": "loc", "cwd": "/w/loc", "host": "local"}
        payload = {"sessions": [dict(local)], "closed": [dict(local)], "retired": [dict(local)]}
        with mock.patch.object(web_hosts.hosts_mod, "load_hosts", lambda: [{"name": "far"}]), \
                mock.patch.object(web_hosts, "get_cached", lambda h: cached), \
                mock.patch.object(web_hosts, "load_settings", lambda: {"fleet_sort": sort}):
            return web_hosts.merge_status(payload)

    def test_missing_null_or_non_text_name_and_cwd_do_not_break_the_merge(self):
        bad = [{"host": "far"}, {"host": "far", "name": None, "cwd": None}, {"host": "far", "name": 5, "cwd": ["x"]},
               {"host": "far", "name": "zzz"}, {"host": "far", "cwd": "/a"}]
        for sort in ("name", "cwd"):
            merged = self.merge(bad, sort)
            for key in ("sessions", "closed", "retired"):
                self.assertEqual(len(merged[key]), len(bad) + 1, (sort, key))

    def test_unusable_values_sort_as_empty_text(self):
        merged = self.merge([{"name": "zzz", "cwd": "/z"}, {"name": 7, "cwd": "/b"}, {"cwd": "/a"}])
        self.assertEqual([r.get("cwd") for r in merged["sessions"]], ["/a", "/b", "/w/loc", "/z"])
        self.assertEqual(merged["sessions"][1]["name"], 7)          # satır değiştirilmez, yalnız sıralama anahtarı boş


class RemoteShapeTest(unittest.TestCase):
    """Nesne olmayan satır ve dizi olmayan `sessions`: istisna yok, poller durumu yazar."""

    HOSTS = [{"name": n, "base_url": f"https://{n}.invalid", "token": "t"} for n in ("bad", "good")]

    def setUp(self):
        self.replies = {}

        def http(method, url, body, timeout, dedup=False):
            name = url.split("//")[1].split(".")[0]
            return 200, self.replies[name], None
        for p in (mock.patch.object(web_hosts, "_http_json", http),
                  mock.patch.object(web_hosts.hosts_mod, "load_hosts", lambda: list(self.HOSTS)),
                  mock.patch.object(web_hosts, "_ensure_status_consumer", lambda h: False),
                  mock.patch.object(web_hosts, "_reap_status_consumers", lambda names: None),
                  mock.patch.dict(web_hosts._cache, clear=True),
                  mock.patch.dict(web_hosts._last_good, clear=True),
                  mock.patch.dict(web_hosts._last_ok_at, clear=True),
                  mock.patch.dict(web_hosts._last_try_at, clear=True),
                  mock.patch.dict(web_hosts._fail_streak, clear=True)):
            p.start()
            self.addCleanup(p.stop)

    def test_non_object_rows_are_skipped(self):
        junk = [5, "ab", None, ["x"], [["name", "sahte"]], True, {"name": "a"}]
        res = web_hosts._finalize_remote_result("h", {"ok": True, "sessions": junk, "closed": junk, "retired": junk})
        for key in ("sessions", "closed", "retired"):
            self.assertEqual(res[key], [{"name": "a", "host": "h"}], key)

    def test_non_list_closed_and_retired_are_empty(self):
        for wrong in (5, True, "ab", {"name": "a"}):
            res = web_hosts._finalize_remote_result("h", {"ok": True, "sessions": [], "closed": wrong, "retired": wrong})
            self.assertEqual((res["closed"], res["retired"]), ([], []), wrong)

    def test_non_list_sessions_is_an_unexpected_shape(self):
        for wrong in (5, None, True, "ab", {"name": "a"}):
            self.replies["bad"] = {"sessions": wrong}
            res = web_hosts.fetch_remote_status(self.HOSTS[0])
            self.assertEqual((res["ok"], res["error"], res["sessions"]), (False, "unexpected response shape", []), wrong)

    def test_one_bad_host_does_not_end_the_poll_turn(self):
        self.replies = {"bad": {"sessions": 5}, "good": {"sessions": [{"name": "g"}, 7]}}
        web_hosts._poll_once()
        self.assertEqual(web_hosts.get_cached("bad")["error"], "unexpected response shape")
        self.assertEqual(web_hosts.get_cached("good")["sessions"], [{"name": "g", "host": "good"}])

    def test_push_frame_without_a_session_list_is_skipped(self):
        for data in ({"sessions": 5}, {"sessions": None}, {"sessions": {"name": "a"}}, {}):
            frame = json.dumps({"type": "status", "data": data})
            self.assertIsNone(web_hosts._parse_ws_status_frame(frame), data)
        ok = web_hosts._parse_ws_status_frame(json.dumps({"type": "status", "data": {"sessions": [1, {"name": "a"}]}}))
        self.assertEqual(web_hosts._finalize_remote_result("h", ok)["sessions"], [{"name": "a", "host": "h"}])


if __name__ == "__main__":
    unittest.main()
