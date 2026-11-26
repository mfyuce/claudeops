"""Güvenilmeyen uzak `/api/status` biçimi (TBD#372): bozuk satır/alan yerel birleştirmeyi ve poller turunu düşürmez.
Gerçek ağ/uzak host YOK; host listesi, ayarlar ve HTTP yanıtı sahte."""
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


if __name__ == "__main__":
    unittest.main()
