"""Altın vektörler: aynı girdiler Python'dan (`py/claudeops`, salt okunur) geçirilir, çıktılar
`tests/golden/` altına yazılır; Rust `tests/golden.rs` aynı dosyaları okuyup kendi çıktısıyla karşılaştırır.

Koşum (repo kökünden):  python3 -I rust/crates/cops-procscan/parity/gen_golden.py
Yazdığı tek yer `rust/crates/cops-procscan/tests/golden/` (+ geçici dizin). Canlı süreç/transkript OKUMAZ.
Python sürümüne bağlıdır (`fromisoformat` 3.11'de genişledi): dosyaya sürüm yazılır, test yalnız bilgi verir.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pyenv  # noqa: E402

OUT = pyenv.HERE.parent / "tests" / "golden"
TMP = pyenv.setup(extra_allowed=[str(OUT)])

from claudeops import discovery, mirrors, needs_ho, session_usage as su  # noqa: E402
from claudeops.providers import PROVIDERS  # noqa: E402
from claudeops.providers.claude_provider import _encode_cwd  # noqa: E402
from claudeops.session import Session  # noqa: E402

RFH = "READY FOR HANDOVER"


def rfh_cases():
    texts = [
        "", RFH, f"  {RFH}", f"\t{RFH}", f"## {RFH} (x)", f"**{RFH}**", f"#*# * {RFH}", f"> {RFH}", f"`{RFH}`",
        f"x {RFH}", f"{RFH}X", RFH.lower(), f"- {RFH}", f"1. {RFH}", f"\u00a0{RFH}", f"\u3000{RFH}", f"\u200b{RFH}",
        f"\x1f{RFH}", f"\x1c{RFH}", f"a\x85{RFH}", f"a\u2028{RFH}", f"a\r{RFH}", f"a\r\n{RFH}", f"a\v{RFH}",
        f"```\n{RFH}\n```", f"   ```py\n{RFH}\n```", f"```\n```\n{RFH}", f"````\n{RFH}", f"~~~\n{RFH}\n~~~",
        f"```\nx\n````\n{RFH}", f"``` ```\n{RFH}", f"özet\n\n## {RFH} (26 Kas)\n- devam", f"#\n#{RFH}",
        f"\ufeff{RFH}", f"*\t#  {RFH}", f"```\n{RFH}", f"a\n```b\n{RFH}\n```\n{RFH}", f"**\u00a0{RFH}", f"_{RFH}_",
    ]
    return [[t, needs_ho.rfh_marker_in(t)] for t in texts]


def name_cases():
    names = ["hc", "hc58", "cops20260824_1", "mo_1_2", "a_", "a1b", "a\u0661", "hc1\n", "a\u00b2", "Hc1", "claude@x#1",
             "", "a_1_", "a__1", "ğ1", "a1_2_3", "a\u0660_\u0661", "abc\n\n", "x1\r"]
    base = [[n, Session(name=n, pid=1).base] for n in names]
    fb = [[c, w, p, discovery.fallback_name(c, w, p)] for c, w, p in [
        ("ucli", "/a/b/", 5), ("shell", "/", 5), ("codex", "/a/b/revdev/", 7), ("agy", "//", 1), ("x", "rel", 2),
        ("x", "/a b/ç d", 3), ("x", "/a//", 4)]]
    cwds = ["/a_b/veri_madenciliği.x", "/", "", "/tmp/a.b-c_d", "/ev/Ünite 3/İ", "/x/\u0661\u0662", "/x/😀"]
    enc = [[c, _encode_cwd(c)] for c in cwds]
    toks = [0, 5, 999, 1000, 1049, 1050, 1051, 9999, 99949, 99950, 999949, 999950, 999999, 1_000_000, 1_004_999,
            1_005_000, 1_234_567, 12345, 10**12, 2**53 + 1, 2**63 - 1]
    fmt = [[n, su.fmt_tokens(n)] for n in toks]
    return {"base": base, "fallback_name": fb, "encode_cwd": enc, "fmt_tokens": fmt}


def committed_after_cases():
    isos = ["", "2026-11-04", "2026-11-04T10", "2026-11-04T10:00", "2026-11-04T10:00:00", "2026-11-04T10:00:00.123",
            "2026-11-04T10:00:00.123456", "2026-11-04T10:00:00.1234", "2026-11-04T10:00:00Z", "2026-11-04T10:00:00+03:00",
            "2026-11-04T10:00:00-01:30", "2026-11-04T10:00:00+0300", "2026-11-04T10:00:00+03",
            "2026-11-04T10:00:00+03:00:30", "2026-11-04T10:00:00+03:00:30.123456", "2026-11-04 07:00:00+00:00",
            "2026-11-04x07:00:00", "2026-11-04ğ07:00", "2026-W45", "20261104", "2026-11-4", "2024-02-29", "2100-02-29",
            "2026-11-04T24:00", "2026-11-04T10:60", "2026-11-04T10:00:60", "2026-11-04T10:00:00+24:00",
            "2026-11-04T10:00:00+23:59", "0001-01-01", "9999-12-31T23:59:59.999999", "bozuk", "2026-11-04T",
            "\u0662\u0660\u0662\u0666-11-04"]
    bases = isos + [" 2026-11-04T09:00:00+03:00\n", "2026-11-04T10:00:00+03:00 "]
    needs_ho._is_git_repo = lambda cwd: True
    needs_ho._repo_baseline_get = lambda cwd: ""
    ts = needs_ho._STATE_DIR / "last-handover.ts"
    out = []
    for ci in isos:
        needs_ho._git = lambda cwd, *a, _ci=ci: _ci
        for b in bases:
            ts.write_text(b)
            out.append([ci, b, needs_ho.repo_committed_since("/x")])
    ts.unlink()
    return out


def provider_cases():
    argvs = [
        "/usr/bin/claude --x", "bash -c claude", "codex", "codex resume u", "codex app-server", "codex exec x",
        "copilot --server --stdio", "copilot --stdio", "ucli chat x", "ucli chat --repl", "claudeops-shell -", "claude/",
        "claude/.", "claude --remote-control a --resume S --model m --permission-mode auto --effort max", "claude --model",
        "claude --resume", "claude --resume --model x",
        "codex resume U --sandbox read-only --ask-for-approval on-request -c model_reasoning_effort=high",
        "codex --sandbox read-only", "codex --sandbox workspace-write --ask-for-approval never",
        "codex --sandbox workspace-write --ask-for-approval on-request --dangerously-bypass-approvals-and-sandbox",
        "codex --sandbox read-only --ask-for-approval never", "codex --config model_reasoning_effort=low -c x=1",
        "codex -c model_reasoning_effort= -c model_reasoning_effort=high", "codex -c", "codex resume",
        "copilot", "copilot --yolo", "copilot --mode plan --yolo", "copilot --reasoning-effort low",
        "copilot --effort  --reasoning-effort low", "copilot --mode autopilot", "copilot --autopilot --mode plan",
        "copilot --allow-all", "copilot --resume r --model m",
        "ucli chat --repl --session s --max-steps 200 --max-tool-calls 256 --max-output-tokens 16000",
        "ucli chat --repl --session s --max-steps 200 --max-tool-calls 256 --max-output-tokens 16000 --max-context-kib 16384",
        "ucli chat --repl --session s --max-steps 200 --max-tool-calls 256 --max-output-tokens 16000 --max-context-kib 1",
        "ucli chat --repl --max-steps 25 --max-context-kib 256 --max-tool-calls 64 --max-output-tokens 4096",
        "ucli chat --repl --max-steps 25 --max-steps 200 --max-tool-calls 256 --max-output-tokens 16000",
        "ucli --repl --allow-edit", "ucli --repl --allow-create --model a --model b", "ucli --repl --model",
        "ucli --repl --session", "agy --conversation c1 --model m --mode plan", "agy --mode accept-edits --effort high",
        "agy --dangerously-skip-permissions --mode plan", "agy --conversation", "claudeops-shell --model x",
    ]
    out = []
    for a in argvs:
        cmd = a.split(" ")
        prov = next((p for p in PROVIDERS.values() if p.matches_proc(cmd)), None)
        info = prov.extract_info(cmd, cwd="", session_name="") if prov else None
        out.append([cmd, prov.name if prov else None, info])
    out.append([[], None, None])
    specs = []
    for a in ["python3 -m claudeops watch yuhem:a", "python3 -m claudeops watch a", "python3 -m claudeops watch --port 1 a",
              "python3 -m claudeops watch h:a --transport ws --follow", "python3 -m claudeops watch a --once",
              "python3 -m claudeops watch :a", "python3 -m claudeops watch h:", "python3 -m claudeops watch",
              "python3 -m claudeops watch --port 1", "python3 -m claudeops list x", "watch claudeops x",
              "claudeops list x", "x claudeops watch  a", "x claudeops watch h: a", "x claudeops watch a:b:c",
              "x claudeops watch  h :  a ", "x claudeops watch --port --once a", "x claudeops watch -v a",
              "x claudeops watch --transport", "claudeops watch a"]:
        cmd = a.split(" ")
        specs.append([cmd, mirrors.spec_from_cmdline(cmd)])
    return {"detect_info": out, "mirror_spec": specs}


def row(t, content, **kw):
    return json.dumps({"type": t, "message": {"content": content}, **kw}, ensure_ascii=False).encode() + b"\n"


def transcript_cases():
    m = f"## {RFH}"
    txt = lambda s: [{"type": "text", "text": s}]  # noqa: E731
    cases = {
        "empty": b"",
        "user_then_rfh": row("user", "iş") + row("assistant", txt(m)),
        "rfh_then_user": row("assistant", txt(m)) + row("user", "bir iş daha"),
        "rfh_then_tool_result": row("assistant", txt(m)) + row("user", [{"type": "tool_result"}, {"type": "text", "text": "x"}]),
        "user_mentions_rfh": row("user", txt(f"bitince '{RFH}' de")) + row("assistant", txt("tamam")),
        "system_rfh": row("system", txt(m)) + row("api-request-blob", m) + row("attachment", m),
        "meta_and_sidechain": row("user", "x", isMeta=True) + row("user", "y", isSidechain=True) + row("user", "  "),
        "string_content": row("user", "x") + row("assistant", m),
        "rfh_in_code": row("user", "x") + row("assistant", txt(f"```\n{RFH}\n```")),
        "broken_lines": b"\n{bozuk\n\xff\xfe\r" + row("user", "x").rstrip(b"\n") + b"\r"
                        + b'{"type":"assistant","message":{"content":"READY FOR HANDOVER \\ud800"}}',
        "crlf": row("user", "x").replace(b"\n", b"\r\n") + row("assistant", m).replace(b"\n", b"\r\n"),
        "non_object_line": row("user", "x") + b"123\n",
        "array_line": b"[]\n" + row("user", "x"),
        "message_null": b'{"type":"user","message":null}\n',
        "message_string": b'{"type":"user","message":"x"}\n' + row("assistant", m),
        "text_not_string": row("user", [{"type": "text", "text": 1}]),
        "text_missing": row("user", [{"type": "text"}]) + row("assistant", m),
        "blocks_not_dicts": row("user", ["x", 1, None, {"type": "text", "text": "y"}]) + row("assistant", m),
        "content_number": row("user", 5) + row("assistant", m),
        "no_type": b'{"message":{"content":"x"}}\n',
        "rfh_text_list_joined": row("user", "x") + row("assistant", [{"type": "text", "text": "a"},
                                                                     {"type": "text", "text": f"\n{RFH}"}]),
        "assistant_text_not_string": row("user", "x") + row("assistant", [{"type": "text", "text": None}]),
        "nan_line": row("user", "x") + b'{"type":"assistant","message":{"content":"' + RFH.encode() + b'"},"n":NaN}\n',
        "dup_keys": row("user", "x") + b'{"type":"user","type":"assistant","message":{"content":"' + RFH.encode() + b'"}}\n',
        "meta_falsy": row("user", "x", isMeta=0),
        "lone_surrogate_user": b'{"type":"user","message":{"content":"\\udc00"}}\n',
        "user_whitespace_unicode": row("user", "\u00a0\u3000"),
        "user_sep_chars": row("user", "\x1c\x1f"),
    }
    d = OUT / "transcripts"
    pyenv.rmtree(d)
    d.mkdir(parents=True)
    out = {}
    for name, data in cases.items():
        p = d / f"{name}.jsonl"
        p.write_bytes(data)
        res = {}
        for fn in ("has_real_user_turn", "handover_done"):
            try:
                res[fn] = getattr(needs_ho, fn)(str(p))
            except Exception as e:  # Python'un istisnası: Rust'ta BadTranscript
                res[fn] = {"error": type(e).__name__}
        out[name] = res
    return out


def urow(mid, rid="r", model="claude-sonnet-5-5", out=5, typ="assistant", **extra):
    msg = {"id": mid, "model": model, "usage": {"input_tokens": 10, "output_tokens": out,
                                                 "cache_creation_input_tokens": 2, "cache_read_input_tokens": 3}}
    r = {"type": typ, "requestId": rid, "message": msg}
    r.update(extra)
    return json.dumps(r).encode() + b"\n"


def usage_cases():
    raw = lambda s: s.encode() + b"\n"  # noqa: E731
    cases = {
        "basic": {"main": urow("m1") + urow("m1", out=9) + urow("m1", rid="r2", model="claude-opus-5-5", out=1)},
        "synthetic": {"main": urow("m1") + urow("s", model="<synthetic>")},
        "bad_model_middle": {"main": urow("m1") + urow("m2", model=5) + urow("m3")},
        "bad_model_last": {"main": urow("m1") + urow("m2", model=5)},
        "falsy_model": {"main": urow("m1", model=0) + urow("m2", model=None) + urow("m3", model="")},
        "list_id": {"main": urow("m1") + urow([1])},
        "list_request_id": {"main": urow("m1", rid=[1])},
        "dict_uuid": {"main": urow(None, uuid={"a": 1})},
        "num_ids_equal": {"main": urow(1, rid=1) + urow(1.0, rid=True, out=7) + urow(True, rid=1.0, out=3)},
        "row_vs_pair_key": {"main": urow("row", rid="u1", out=4) + urow(None, uuid="u1", out=8)},
        "no_ids": {"main": urow(None) + urow(None) + urow("", uuid="")},
        "null_vs_missing_rid": {"main": urow("m", rid=None) + raw(json.dumps(
            {"type": "assistant", "message": {"id": "m", "model": "x", "usage": {"output_tokens": 9}}}))},
        "counts_types": {"main": raw(json.dumps({"type": "assistant", "message": {"id": "a", "model": "x", "usage": {
            "input_tokens": "12", "output_tokens": 2.7, "cache_creation_input_tokens": -4, "cache_read_input_tokens": True}}}))
            + raw(json.dumps({"type": "assistant", "message": {"id": "b", "model": "x", "usage": {
                "input_tokens": " 1_0 ", "output_tokens": "1.5", "cache_creation_input_tokens": None,
                "cache_read_input_tokens": [1]}}}))},
        "usage_not_dict": {"main": raw(json.dumps({"type": "assistant", "message": {"id": "x", "usage": "s"}})) + urow("m1")},
        "message_not_dict": {"main": raw(json.dumps({"type": "assistant", "message": "usage"})) + urow("m1")},
        "surrogate_id": {"main": b'{"type":"assistant","requestId":"r","message":{"id":"\\ud800","model":"x","usage":'
                                 b'{"output_tokens":3}}}\n' + urow("m1")},
        "partial_last": {"main": urow("m1") + urow("m2")[:20]},
        "dup_keys": {"main": b'{"type":"user","type":"assistant","message":{"id":"d","model":"x","usage":{"output_tokens":1},'
                             b'"usage":{"output_tokens":6}}}\n' + urow("m1")},
        "invalid_utf8": {"main": b'{"type":"assistant","message":{"id":"z","model":"\xff","usage":{}}}\n' + urow("m1")},
        "families": {"main": urow("a", model="Claude-FABLE-x") + urow("b", model="sonnet-opus") + urow("c", model="HAIKU")},
        "subagents": {"main": urow("m1"), "agent-1.jsonl": urow("m1", model="claude-haiku-5"),
                      "agent-2.jsonl": urow("s2", out=40) + urow("s2", out=2), "other.jsonl": urow("o"),
                      ".agent-h.jsonl": urow("h"), "agent-x.json": urow("j")},
        "subagent_bad": {"main": urow("m1"), "agent-1.jsonl": urow("q", model=[1])},
        "missing": {},
    }
    d = OUT / "usage"
    pyenv.rmtree(d)
    d.mkdir(parents=True)
    out = {}
    for name, files in cases.items():
        cd = d / name
        cd.mkdir()
        main = cd / "s.jsonl"
        for fname, data in files.items():
            if fname == "main":
                main.write_bytes(data)
            else:
                (cd / "s" / "subagents").mkdir(parents=True, exist_ok=True)
                (cd / "s" / "subagents" / fname).write_bytes(data)
        su._files.clear()
        su._summaries.clear()
        out[name] = [su.usage_for_path(str(main)), su.usage_for_path(str(main))]
    return out


def main():
    data = {
        "python": sys.version.split()[0],
        "rfh": rfh_cases(),
        "names": name_cases(),
        "committed_after": committed_after_cases(),
        "providers": provider_cases(),
        "transcripts": transcript_cases(),
        "usage": usage_cases(),
    }
    (OUT / "python.json").write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    assert not pyenv.blocked(), pyenv.blocked()
    pyenv.rmtree(TMP)
    print(f"yazıldı: {OUT} (Python {data['python']})")


if __name__ == "__main__":
    main()
