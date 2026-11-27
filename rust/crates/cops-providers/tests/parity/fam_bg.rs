//! Aile (G6): `bg_work` saf işlevleri: ekran sayımları, transkript/rollout taraması, dosya kuyruğu.
//! Metinler `py/tests/test_bg_work.py` örnekleri + boş/bozuk/Unicode/kısmi satır sınırları.

use crate::common::*;
use cops_providers::bg_work::{self, Clock};
use cops_providers::pyjson::Py;
use cops_providers::Live;
use serde_json::{json, Value};

/// 2026-11-23T10:30:00Z (test_bg_work.py `T`).
pub const T: f64 = 1_795_429_800.0;

const SCREEN_SHELL: &str = "\
· Churning… (8s · ↓ 277 tokens)
────────────────────────────── derbent ─
❯
  ⏵⏵ auto mode on · 1 shell · esc to interrupt · ← 1 agent · ↓ to manage       /rc

● main
○ general-purpose  waiting on 1 shell · Yol öneki rewrite (köke göreli) · since 18:08
";
const SCREEN_BG_TASKS: &str = "❯\n  2 background tasks · ← 1 agent · ↓ to manage\n";
const SCREEN_OWN_WORK: &str =
    "● main\n○ general-purpose  Agent is waiting on its own background work · 40m\n";
const SCREEN_IDLE: &str =
    "● Bitti: 3 agents tamamlandı, 2 shells kapandı.\n❯\n  ⏵⏵ auto mode on · ? for shortcuts\n";
const CODEX_SCREEN: &str =
    "• Başladı.\n  1 background terminal running · /ps to view · /stop to close\n› Ask Codex to do anything\n";

pub fn screens() -> Vec<(&'static str, String)> {
    let mut v: Vec<(&'static str, String)> = vec![
        ("shell", SCREEN_SHELL.into()),
        ("tasks", SCREEN_BG_TASKS.into()),
        ("own", SCREEN_OWN_WORK.into()),
        ("idle", SCREEN_IDLE.into()),
        ("codex", CODEX_SCREEN.into()),
        (
            "codex-idle",
            "› Ask Codex to do anything\nWorked for 3s".into(),
        ),
        ("bos", String::new()),
        ("satir", "\n\n\n".into()),
        ("sifir", "0 background tasks · ↓ to manage".into()),
    ];
    v.extend(
        [
            "10 shells · to manage",
            "1 shell 2 agents 3 monitors 4 background task · ctrl+b",
            "1 SHELL · ESC TO INTERRUPT",
            "1 Shell · To View",
            "x1 shell · to manage",
            "ğ1 shell · to manage",
            "_1 shell · to manage",
            ".1 shell · to manage",
            "v1.2 shells · to manage",
            "(1 shell) · to manage",
            "1 shellx · to manage",
            "1 shellğ · to manage",
            "1 shell_ · to manage",
            "1 shell\u{301} · to manage",
            "1 shell. · to manage",
            "1  shell · to manage",
            "1\u{a0}shell · to manage",
            "01 shell · to manage",
            "1٣ shells · to manage",
            "١ shell · to manage",
            "1𝟘 agents to view",
            "2 monİtors · to manage",
            "2 monıtors · TO MANAGE",
            "2 ſhells · eſc to interrupt",
            "1 bac\u{212a}ground task · to manage",
            "waİtıng on 2 shells",
            "WAITING ON ITS OWN BACKGROUND WORK",
            "awaiting on 2 shells",
            "ğwaiting on 2 shells",
            "-waiting on 2 shells",
            "waiting on 0 shells",
            "waiting on 3 monitors",
            "waiting on 3 monitorsx",
            "waiting on 1 background task",
            "waiting on its own",
            "2 agents\nto manage",
            "to manage 2 agents",
            "5 agents",
            "9 shells · to manage\r",
            "9 shells · to manage\r\n1 shell · to manage\r\n",
            "9 shells · to manage\u{2028}1 shell",
            "1 background terminals running",
            "3 background terminals running · 2 background terminal running",
            "x3 background terminals running",
            "3 BACKGROUND TERMINAL RUNNİNG",
            "1 shell 2 shells to manage",
            "1 shellx 2 shells,3 agents to manage",
            "11 shells to manage",
            "x11 shells to manage",
            "1 shells2 agents to manage",
            "2 background terminals running 3 background terminals running",
            "2 background terminals running3 background terminals running",
            "x waiting on 1 shell waiting on 2 shells",
            "0 background terminal running",
            "12 background terminals runningx",
            // 27 Kas: `← N agent` gezinme ipucu iş sayısı değil
            "⏵⏵ auto mode on (shift+tab to cycle) · ← 1 agent                               /rc",
            "⏵⏵ auto mode on (shift+tab to cycle) · ← 1 agent · ↓ to manage                 /rc",
            "⏵⏵ auto mode on (shift+tab to cycle) · esc to interrupt · ← 1 agent            /rc",
            "⏵⏵ auto mode on · 1 shell · ← 1 agent · ↓ to manage                            /rc",
            "⏵⏵ auto mode on · 3 background tasks · ← 1 agent · ↓ to manage                 /rc",
            "← 3 agents · esc to interrupt",
            "← 2 agents · ↓ to manage",
            "←2 AGENTS to manage",
            "←\u{a0}2 agents to manage",
            "←\u{1c}\u{1f}2 agents to manage",
            "←\t\u{3000}2 agents to manage",
            "←\u{200b}2 agents to manage",
            "← ١ agent to manage",
            "← 0 agents · 1 shell to manage",
            "← 1 agentx to manage",
            "← 1 agentsx to manage",
            "← 1 agentğ to manage",
            "← 1 agent_ to manage",
            "← 1 agent\u{301} to manage",
            "← 1 agent. to manage",
            "← 1  agent to manage",
            "← 1\u{a0}agent to manage",
            "← 2 agentſ to manage",
            "→ 1 agent to manage",
            "2← 1 agent shells to manage",
            "← 1 agent← 2 agents 3 agents to manage",
            "← 1 agent waiting on 1 shell",
            "waiting on ← 1 agent",
            "← 4 agents",
        ]
        .iter()
        .map(|s| ("kenar", s.to_string())),
    );
    // son 14 satır sınırı: gösterge 14. ve 15. satırda, sondaki boş satırlar kırpılır
    for n in [12usize, 13, 14, 15] {
        v.push((
            "kuyruk",
            format!("1 shell · to manage\n{}{}", "x\n".repeat(n), "\n".repeat(3)),
        ));
        v.push((
            "kuyruk-codex",
            format!("1 background terminal running\n{}", "x\n".repeat(n)),
        ));
    }
    v
}

fn use_(id: &str, bg: bool, ts: &str) -> String {
    json!({"timestamp": ts, "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": id, "name": "Bash", "input": {"command": "x", "run_in_background": bg}}]}})
    .to_string()
}

pub fn pending_use(id: &str, ts: &str) -> String {
    use_(id, true, ts)
}

fn res(id: &str, content: Value, is_error: Value) -> String {
    json!({"message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": id, "is_error": is_error, "content": content}]}})
    .to_string()
}

fn notif(status: &str, id: Option<&str>, task: Option<&str>) -> String {
    let mut body = String::from("<task-notification>");
    if let Some(t) = task {
        body += &format!("<task-id>{t}</task-id>");
    }
    if let Some(i) = id {
        body += &format!("<tool-use-id>{i}</tool-use-id>");
    }
    body += &format!("<status>{status}</status></task-notification>");
    json!({"message": {"role": "user", "content": body}}).to_string()
}

pub fn sub_agent(kind: &str, id: Value, ts: &str) -> String {
    json!({"timestamp": ts, "type": "event_msg", "payload": {"type": "item_completed", "item": {
        "type": "SubAgentActivity", "kind": kind, "agent_thread_id": id, "agent_path": "/root/x"}}})
    .to_string()
}

fn transcripts() -> Vec<Vec<String>> {
    let ts = "2026-11-23T10:00:00Z";
    let u = |i: &str| use_(i, true, ts);
    let running = |i: &str, t: &str| {
        res(
            i,
            json!(format!("Command running in background with ID: {t}.")),
            json!(null),
        )
    };
    let done = |t: &str| notif("completed", None, Some(t));
    let mut v: Vec<Vec<String>> = vec![
        vec![],
        vec![String::new()],
        // test_bg_work.py
        vec![u("t1"), running("t1", "b1")],
        vec![u("t1"), notif("completed", Some("t1"), None)],
        vec![u("t1"), notif("failed", Some("t1"), None)],
        vec![u("t1"), notif("killed", Some("t1"), None)],
        vec![u("t1"), running("t1", "b1"), done("b1")],
        vec![use_("t1", false, ts)],
        vec![use_("t1", true, "2026-11-23T03:00:00Z")],
        vec![u("t1"), res("t1", json!("Permission denied."), json!(true))],
        vec![u("t1"), u("t2"), res("t1", json!("Permission denied."), json!(true))],
        vec![u("t1"), u("t2"), notif("completed", Some("t1"), None)],
        // durum yazımı ve bitiş sözcükleri
        vec![u("t1"), notif("  CANCELLED \u{1f}", Some("t1"), None)],
        vec![u("t1"), notif("Canceled", Some("t1"), None)],
        vec![u("t1"), notif("stopped", Some("t1"), None)],
        vec![u("t1"), notif("running", Some("t1"), None)],
        vec![u("t1"), notif("KİLLED", Some("t1"), None)],
        vec![u("t1"), notif("", Some("t1"), None)],
        vec![u("t1"), json!({"message": {"content": "<task-notification><tool-use-id>t1</tool-use-id>"}}).to_string()],
        vec![u("t1"), json!({"message": {"content": "<status>completed</status><tool-use-id>t1</tool-use-id>"}}).to_string()],
        // bildirim önce, iş sonra
        vec![notif("completed", Some("t1"), None), u("t1")],
        // is_error yalnız `true` ise düşer
        vec![u("t1"), res("t1", json!("x ID: b1"), json!(1)), done("b1")],
        vec![u("t1"), res("t1", json!("x ID: b1"), json!("true")), done("b1")],
        // görev kimliği: liste içeriği (metin blokları), kaçışlar, sınır, 400 karakter
        vec![u("t1"), res("t1", json!([{"type": "text", "text": "running with ID: b1."}]), json!(false)), done("b1")],
        vec![u("t1"), res("t1", json!([{"type": "text", "text": "a\nID: b1"}]), json!(null)), done("b1")],
        vec![u("t1"), res("t1", json!([{"type": "text", "text": "a'\"b ID: b1"}]), json!(null)), done("b1")],
        vec![u("t1"), res("t1", json!([{"type": "text", "text": "basladi"}, {"type": "text", "text": "ID: b1"}]), json!(null)), done("b1")],
        vec![u("t1"), res("t1", json!([5, {"type": "text", "text": 5}, {"type": "image", "source": "ID: b1"}]), json!(null)), done("b1")],
        vec![u("t1"), res("t1", json!([{"type": "text", "text": format!("{}ID: b1", "x".repeat(399))}]), json!(null)), done("b1")],
        vec![u("t1"), res("t1", json!("a\nID: b1"), json!(null)), done("b1")],
        vec![u("t1"), res("t1", json!("a\u{a0}ID: b1"), json!(null)), done("b1")],
        vec![u("t1"), res("t1", json!(["a\u{a0}ID: b1"]), json!(null)), done("b1")],
        vec![u("t1"), res("t1", json!(["a\u{200b}ID: b1 \u{2028}"]), json!(null)), done("b1")],
        vec![u("t1"), res("t1", json!("PID: b1"), json!(null)), done("b1")],
        vec![u("t1"), res("t1", json!("ğID: b1"), json!(null)), done("b1")],
        vec![u("t1"), res("t1", json!("ID: ğ1"), json!(null)), done("ğ1")],
        vec![u("t1"), res("t1", json!(format!("{}ID: b1", "ğ".repeat(392) + " ")), json!(null)), done("b1")],
        vec![u("t1"), res("t1", json!(format!("{}ID: b123", "x".repeat(393) + " ")), json!(null)), done("b1")],
        vec![u("t1"), res("t1", json!(format!("{}ID: b1", "x".repeat(400))), json!(null)), done("b1")],
        vec![u("t1"), res("t1", json!(null), json!(null)), done("None")],
        vec![u("t1"), res("t1", json!({"k": 1.5, "l": [true, null, -2], "ID: b1": ""}), json!(null)), done("b1")],
        vec![u("t1"), res("yok", json!("ID: b1"), json!(null)), done("b1")],
        // kimlik tipleri: sayı kimlik bildirimdeki metinle eşleşmez; True == 1
        vec![
            r#"{"message":{"content":[{"type":"tool_use","id":5,"input":{"run_in_background":true}}]}}"#.into(),
            notif("completed", Some("5"), None),
        ],
        vec![
            r#"{"message":{"content":[{"type":"tool_use","id":1,"input":{"run_in_background":true}}]}}"#.into(),
            r#"{"message":{"content":[{"type":"tool_result","tool_use_id":true,"is_error":true,"x":"background"}]}}"#.into(),
        ],
        vec![r#"{"message":{"content":[{"type":"tool_use","id":"","input":{"run_in_background":true}}]}}"#.into()],
        vec![r#"{"message":{"content":[{"type":"tool_use","id":0,"input":{"run_in_background":true}}]}}"#.into()],
        vec![r#"{"message":{"content":[{"type":"tool_use","input":{"run_in_background":true}}]}}"#.into()],
        vec![r#"{"message":{"content":[{"type":"tool_use","id":"t","input":{"run_in_background":1}}]}}"#.into()],
        vec![r#"{"message":{"content":[{"type":"tool_use","id":"t","input":null,"run_in_background":true}]}}"#.into()],
        vec![r#"{"message":null,"x":"background"}"#.into(), u("t1")],
        vec![r#"{"message":[],"x":"background"}"#.into(), u("t1")],
        vec![r#"{"message":{"content":7},"x":"background"}"#.into()],
        vec![r#"{"message":{"content":["background",1,null]}}"#.into(), u("t1")],
        vec![r#"{"x":"background"}"#.into()],
        // bozuk / kısmi satırlar
        vec!["{\"run_in_background\"".into(), u("t1")],
        vec![u("t1"), notif("completed", Some("t1"), None)[..40].to_string()],
        vec!["background".into(), u("t1")],
        vec![format!("\u{feff}{}", u("t1"))],
        vec![format!("{}\r", u("t1"))],
        vec![format!("  {}  ", u("t1"))],
        vec![format!("{} x", u("t1"))],
        // Python json: NaN, eşlenmemiş vekil (kesik emoji), büyük sayı, yinelenen anahtar
        vec![u("t1").replacen('{', "{\"n\":NaN,\"i\":-Infinity,\"b\":123456789012345678901234567890,", 1)],
        vec![u("t1").replacen('{', "{\"s\":\"\\ud83d\",", 1)],
        vec![u("t1"), notif("completed", Some("t1"), None).replacen('{', "{\"s\":\"\\ud83d\\u0041\",", 1)],
        vec![u("t1").replacen('{', "{\"message\":1,", 1)],
    ];
    // TaskStop/KillShell ile durdurma ve tur ortasında gelen bildirim (test_bg_work.py + kenarlar)
    let stop = |tool: &str, input: Value, is_error: Value| {
        vec![
            json!({"message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "s1", "name": tool, "input": input}]}})
            .to_string(),
            res("s1", json!("Successfully stopped task: b1 (x)"), is_error),
        ]
    };
    let started = || vec![u("t1"), running("t1", "b1")];
    for (tool, input, is_error) in [
        ("TaskStop", json!({"task_id": "b1"}), json!(null)),
        ("TaskStop", json!({"shell_id": "b1"}), json!(false)),
        ("KillShell", json!({"shell_id": "b1"}), json!(null)),
        (
            "TaskStop",
            json!({"task_id": "", "shell_id": "b1"}),
            json!(null),
        ),
        (
            "TaskStop",
            json!({"task_id": 0, "shell_id": "b1"}),
            json!(null),
        ),
        (
            "TaskStop",
            json!({"task_id": "b2", "shell_id": "b1"}),
            json!(null),
        ),
        ("TaskStop", json!({"task_id": "b1"}), json!(true)),
        ("TaskStop", json!({"task_id": "b1"}), json!(1)),
        ("TaskStop", json!({"task_id": "b2"}), json!(null)),
        ("TaskStop", json!({}), json!(null)),
        ("TaskStop", json!({"task_id": ["b1"]}), json!(null)),
        (
            "TaskStop",
            json!({"task_id": "b1", "run_in_background": true}),
            json!(null),
        ),
        ("taskstop", json!({"task_id": "b1"}), json!(null)),
        ("Bash", json!({"task_id": "b1"}), json!(null)),
    ] {
        let mut lines = started();
        lines.extend(stop(tool, input, is_error));
        v.push(lines);
    }
    // sonuç henüz yok; sonuç çağrıdan önce; ikinci sonuç; sayı hedef
    let by_id = stop("TaskStop", json!({"task_id": "b1"}), json!(null));
    v.push([started(), vec![by_id[0].clone()]].concat());
    v.push([started(), vec![by_id[1].clone(), by_id[0].clone()]].concat());
    v.push([by_id.clone(), started()].concat());
    v.push([started(), by_id.clone(), vec![by_id[1].clone()]].concat());
    v.push(
        [
            vec![u("t1"), running("t1", "7")],
            stop("TaskStop", json!({"task_id": 7}), json!(null)),
        ]
        .concat(),
    );
    v.push(
        [
            vec![u("t1"), running("t1", "True")],
            stop("TaskStop", json!({"task_id": true}), json!(null)),
        ]
        .concat(),
    );
    let body = "<task-notification>\n<task-id>b1</task-id>\n<tool-use-id>t1</tool-use-id>\n<status>completed</status>\n</task-notification>";
    let quoted = format!("şu bildirimi gördün mü: {body}");
    for record in [
        json!({"type": "queue-operation", "operation": "enqueue", "content": body}),
        json!({"type": "queue-operation", "operation": "enqueue", "content": quoted}),
        json!({"type": "queue-operation", "content": [body]}),
        json!({"type": "queue-operation", "content": "x", "message": {"content": body}}),
        json!({"type": "attachment", "attachment": {"type": "queued_command", "commandMode": "task-notification", "prompt": body}}),
        json!({"type": "attachment", "attachment": {"commandMode": "task-notification", "prompt": quoted}}),
        json!({"type": "attachment", "attachment": {"commandMode": "prompt", "prompt": body}}),
        json!({"type": "attachment", "attachment": {"commandMode": "task-notification", "prompt": [body]}}),
        json!({"attachment": {"commandMode": "prompt"}, "message": {"content": body}}),
        json!({"attachment": "x", "message": {"content": body}}),
        json!({"type": "queue-operation", "message": "x", "content": body}),
    ] {
        v.push([started(), vec![record.to_string()]].concat());
    }
    // 27 Kas: araç çağrısı/sonucu yalnız ileti kaydından (türsüz, `assistant`, `user`); `api-request-blob` isteğin kopyası
    for kind in [
        json!(null),
        json!("assistant"),
        json!("user"),
        json!("api-request-blob"),
        json!("attachment"),
        json!("queue-operation"),
        json!("system"),
        json!("Assistant"),
        json!(""),
        json!(0),
        json!(false),
        json!(["assistant"]),
        json!({"a": "user"}),
    ] {
        let typed = |line: &str| line.replacen('{', &format!("{{\"type\":{kind},"), 1);
        let refused = res("t1", json!("no verdict"), json!(true));
        v.push(vec![typed(&u("t1"))]);
        v.push(vec![typed(&u("t1")), refused.clone()]);
        v.push(vec![u("t1"), refused, typed(&u("t1"))]);
        v.push(vec![u("t1"), typed(&res("t1", json!("x"), json!(true)))]);
        v.push(vec![
            u("t1"),
            typed(&res("t1", json!("ID: b1"), json!(null))),
            done("b1"),
        ]);
        let mut stopped = started();
        stopped.extend(by_id.iter().map(|l| typed(l)));
        v.push(stopped);
        v.push(vec![u("t1"), typed(&notif("completed", Some("t1"), None))]);
    }
    // zaman damgası biçimleri (yaş sınırı 6 saat)
    for stamp in [
        "2026-11-23T10:00:00.123Z",
        "2026-11-23T04:30:00Z",
        "2026-11-23T04:30:01Z",
        "2026-11-23T04:29:59.999999Z",
        "2026-11-23T07:30:00+03:00",
        "2026-11-23T01:00:00-03:30",
        "2026-11-23T07:30:01+03:00:00",
        "2026-11-23T07:30:01+03:00:00.000001",
        "2026-11-23 01:00:00Z",
        "2026-11-23ğ01:00:00Z",
        "2026-11-23T01Z",
        "2026-11-23T01:00Z",
        "2026-11-23T01:00:00",
        "2026-11-23T05:00:00",
        "2026-11-23",
        "2026-11-22",
        "2026-11-23T",
        "2026-11-23T25:00:00Z",
        "2026-02-30T01:00:00Z",
        "2024-02-29T01:00:00Z",
        "2026-11-23T01:00:00.1Z",
        "2026-11-23T01:00:00.1234Z",
        "2026-11-23T01:00:00+3",
        "2026-11-23T01:00:00+25:00",
        "2026-11-23T01:00:00x",
        "20261123T010000",
        "1970-01-01T00:00:00Z",
        "0000-01-01T00:00:00Z",
        "dün",
        "",
        "Z",
    ] {
        v.push(vec![use_("t1", true, stamp)]);
        v.push(vec![sub_agent("started", json!("a"), stamp)]);
    }
    // 4300 basamaktan uzun sayı: `ValueError`, satır atlanır
    v.push(vec![
        format!("{{\"run_in_background\":{}}}", "9".repeat(5000)),
        use_("t1", true, "2026-11-23T10:00:00Z"),
    ]);
    v.push(vec![r#"{"timestamp":5,"message":{"content":[{"type":"tool_use","id":"t","input":{"run_in_background":true}}]}}"#.into()]);
    // codex alt ajanları (test_bg_work.py + kenarlar)
    let a = |k: &str, i: Value| sub_agent(k, i, "2026-11-23T10:17:26Z");
    v.extend([
        vec![a("started", json!("a1")), a("started", json!("a2")), a("completed", json!("a1"))],
        vec![a("started", json!("a1")), a("failed", json!("a1"))],
        vec![a("started", json!("a1")), a("cancelled", json!("a1"))],
        vec![a("started", json!("a1")), a("canceled", json!("a1"))],
        vec![a("started", json!("a1")), a("closed", json!("a1"))],
        vec![a("started", json!("a1")), a("progress", json!("a1"))],
        vec![a("closed", json!("a1")), a("started", json!("a1"))],
        vec![a("started", json!(7)), a("completed", json!("7"))],
        vec![a("started", json!(["x", 1])), a("started", json!({"y": null})), a("completed", json!(["x", 1]))],
        vec![a("started", json!("")), a("started", json!(0)), a("started", json!(null)), a("started", json!(false))],
        vec![a("started", json!(true)), a("started", json!(1.5))],
        vec![a("started", json!("a1")), a("started", json!("a1"))],
        vec![r#"{"payload":null,"x":"SubAgentActivity"}"#.into(), a("started", json!("a1"))],
        vec![r#"{"payload":{"item":null},"x":"SubAgentActivity"}"#.into(), a("started", json!("a1"))],
        vec![r#"{"payload":{"item":{"type":"x","agent_thread_id":"a"}},"x":"SubAgentActivity"}"#.into()],
        vec!["SubAgentActivity {".into(), a("started", json!("a1"))],
        vec![r#"{"payload":{"item":{"type":"SubAgentActivity","kind":["started"],"agent_thread_id":"a"}}}"#.into()],
        vec![r#"{"payload":{"item":{"type":"SubAgentActivity","kind":"started","agent_thread_id":"a"}}}"#.into()],
    ]);
    v
}

/// Python'da TÜM taramayı düşüren satırlar (Rust satırı atlayıp sürdürür); her biri ardından geçerli bir iş gelir.
fn odd_lines() -> Vec<(&'static str, Vec<String>)> {
    let good = use_("t1", true, "2026-11-23T10:00:00Z");
    let agent = sub_agent("started", json!("a1"), "2026-11-23T10:17:26Z");
    let c = |bad: &str| vec![bad.to_string(), good.clone()];
    let x = |bad: &str| vec![bad.to_string(), agent.clone()];
    vec![
        ("belge-metin", c("\"background\"")),
        ("belge-liste", c("[\"background\"]")),
        ("mesaj-metin", c(r#"{"message":"background"}"#)),
        (
            "girdi-metin",
            c(r#"{"message":{"content":[{"type":"tool_use","id":"z","input":"background"}]}}"#),
        ),
        (
            "kimlik-liste",
            c(
                r#"{"message":{"content":[{"type":"tool_use","id":["z"],"input":{"run_in_background":true}}]}}"#,
            ),
        ),
        (
            "sonuc-kimlik-liste",
            c(
                r#"{"message":{"content":[{"type":"tool_result","tool_use_id":["z"],"x":"background"}]}}"#,
            ),
        ),
        (
            "ad-liste",
            c(
                r#"{"message":{"content":[{"type":"tool_use","id":"z","name":["TaskStop"],"x":"background"}]}}"#,
            ),
        ),
        (
            "durdurma-girdi-metin",
            c(
                r#"{"message":{"content":[{"type":"tool_use","id":"z","name":"TaskStop","input":"b1"}]}}"#,
            ),
        ),
        (
            "durdurma-kimlik-liste",
            c(
                r#"{"message":{"content":[{"type":"tool_use","id":["z"],"name":"TaskStop","input":{}}]}}"#,
            ),
        ),
        ("rollout-belge", x("\"SubAgentActivity\"")),
        ("rollout-payload", x(r#"{"payload":"SubAgentActivity"}"#)),
        (
            "rollout-item",
            x(r#"{"payload":{"item":"SubAgentActivity"}}"#),
        ),
    ]
}

/// Belirlenimci sözde rastgele sayı (LCG).
pub struct Rng(pub u64);

impl Rng {
    pub fn below(&mut self, n: usize) -> usize {
        self.0 = self
            .0
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1_442_695_040_888_963_407);
        (self.0 >> 33) as usize % n
    }
    pub fn soup(&mut self, tokens: &[&str], max: usize) -> String {
        (0..self.below(max))
            .map(|_| tokens[self.below(tokens.len())])
            .collect()
    }
}

/// Ekran satırı sözcükleriyle rastgele metinler (sınır koşulları: bitişik sözcük, rakam, harf).
fn random_screens() -> Vec<String> {
    const T: &[&str] = &[
        "1",
        "2",
        "10",
        "0",
        "٣",
        " ",
        " ",
        " ",
        "shell",
        "shells",
        "agent",
        "monitor",
        "s",
        "x",
        "ğ",
        "_",
        ".",
        ",",
        "·",
        "\n",
        "background",
        " task",
        "terminal",
        " running",
        "waiting",
        " on ",
        "its own background work",
        "to manage",
        "esc to interrupt",
        "to view",
        "ctrl+b",
        "←",
        "←",
        "agents",
        " 2 agents",
        "\u{1c}",
        "İ",
        "ſ",
        "\u{301}",
        "-",
        "(",
    ];
    let mut r = Rng(1);
    (0..3000).map(|_| r.soup(T, 14)).collect()
}

/// Geçerli bir damganın rastgele bozulmuş biçimleri.
pub fn random_stamps() -> Vec<String> {
    const T: &[&str] = &[
        "0", "1", "2", "3", "5", "9", "-", "+", ":", ".", "T", " ", "Z", "ğ", "x", "00", "12",
        "59", "60", "24",
    ];
    let mut r = Rng(2);
    let bases = [
        "2026-11-23T10:00:00.123+03:00",
        "2026-11-23T10:00:00Z",
        "2026-02-28 23:59:59.999999",
        "2024-02-29T00",
        "0001-01-02T00:00:00+00:00",
        "2199-12-30T23:59:59-23:59",
        "2026-11-23T10:00:00+03:00:00.000001",
    ];
    let mut out: Vec<String> = bases.iter().map(|s| s.to_string()).collect();
    for _ in 0..6000 {
        let mut c: Vec<char> = bases[r.below(bases.len())].chars().collect();
        for _ in 0..1 + r.below(3) {
            let at = r.below(c.len() + 1);
            match r.below(4) {
                0 if at < c.len() => {
                    c.remove(at);
                }
                1 if at < c.len() => c
                    .splice(at..=at, T[r.below(T.len())].chars())
                    .for_each(drop),
                2 => c.truncate(at),
                _ => c.splice(at..at, T[r.below(T.len())].chars()).for_each(drop),
            }
        }
        out.push(c.into_iter().collect());
    }
    // Yıl sınırları atılır: Python yerel saat aritmetiği 1. ve 9999. yılda taşar; 2^53 mikro saniyeyi aşan yıllarda
    // (~2255 sonrası) `int / int` ile `f64` bölmesi son bitte ayrışabilir (yaş karşılaştırmasını etkilemez).
    out.retain(|s| {
        let far = s
            .get(..4)
            .and_then(|y| y.parse::<u32>().ok())
            .is_some_and(|y| y > 2200);
        !(far || s.starts_with("0000") || s.starts_with("0001-01-01"))
    });
    out
}

fn clock(case: &Case) -> Clock {
    let offset = if case.args["tz"] == "UTC0" {
        0
    } else {
        3 * 3600
    };
    Clock {
        now: case.args["now"].as_f64().unwrap(),
        utc_offset_secs: offset,
    }
}

fn rs_bg(e: &Env, c: &Case) -> RsOut {
    let clock = clock(c);
    let settings = e.settings();
    let paths = e.paths();
    let probe = FsProbe::new(e, c);
    let live = Live {
        settings: &settings,
        paths: &paths,
        probe: &probe,
        clock,
    };
    let texts = strs(c.args.get("texts"));
    let transcripts: Vec<Vec<String>> = c
        .args
        .get("transcripts")
        .and_then(Value::as_array)
        .map(|a| a.iter().map(|t| strs(Some(t))).collect())
        .unwrap_or_default();
    let files = strs(c.args.get("files"));
    RsOut::ret(json!({
        "screen_bg_count": texts.iter().map(|t| bg_work::screen_bg_count(t)).collect::<Vec<_>>(),
        "screen_bg_work": texts.iter().map(|t| bg_work::screen_bg_work(t)).collect::<Vec<_>>(),
        "codex_screen_count": texts.iter().map(|t| bg_work::codex_screen_count(t)).collect::<Vec<_>>(),
        "transcript_pending": transcripts.iter()
            .map(|ls| bg_work::transcript_pending(ls.iter().map(String::as_str), clock)).collect::<Vec<_>>(),
        "codex_subagents_pending": transcripts.iter()
            .map(|ls| bg_work::codex_subagents_pending(ls.iter().map(String::as_str), clock)).collect::<Vec<_>>(),
        "transcript_pending_path": files.iter().map(|f| live.transcript_pending_path(Some(f))).collect::<Vec<_>>(),
        "tail_lines": files.iter().map(|f| live.tail_lines(Some(f))).collect::<Vec<_>>(),
        "tail_bytes": bg_work::TRANSCRIPT_TAIL_BYTES,
        "epochs": strs(c.args.get("stamps")).iter()
            .map(|s| bg_work::iso_epoch(&Py::Str(s.clone()), clock.utc_offset_secs)).collect::<Vec<_>>(),
    }))
}

fn cases(e: &Env) -> Vec<Case> {
    let mut v = Vec::new();
    let texts: Vec<String> = screens().into_iter().map(|(_, t)| t).collect();
    v.push(Case::new(
        "bg-ekran",
        "bg",
        json!({"texts": texts, "now": T, "tz": "UTC0"}),
    ));
    v.push(Case::new(
        "bg-ekran-rastgele",
        "bg",
        json!({"texts": random_screens(), "now": T, "tz": "UTC0"}),
    ));
    for tz in ["UTC0", "XXX-3"] {
        v.push(Case::new(
            format!("bg-damga-{tz}"),
            "bg",
            json!({"stamps": random_stamps(), "now": T, "tz": tz}),
        ));
    }
    let all = transcripts();
    for (i, chunk) in all.chunks(8).enumerate() {
        for (tz, now) in [("UTC0", T), ("XXX-3", T), ("UTC0", T + 7.0 * 3600.0)] {
            v.push(Case::new(
                format!("bg-transkript-{i}-{tz}-{now}"),
                "bg",
                json!({"transcripts": chunk, "now": now, "tz": tz}),
            ));
        }
    }
    // beklenmeyen tipte satır: iki tarafta da yalnız o satır/blok atlanır; sağlam satır sayılmaya devam eder
    for (name, lines) in odd_lines() {
        v.push(Case::new(
            format!("bg-sekil-{name}"),
            "bg",
            json!({"transcripts": [lines], "now": T, "tz": "UTC0"}),
        ));
    }
    // dosya kuyruğu: yok, dizin, boş yol, boş dosya, bozuk UTF-8, yarım satır, 8 MiB sınırında kesilen kayıt
    let path = |rel: &str| format!("{}/{rel}", e.root);
    let good = use_("t1", true, "2026-11-23T10:00:00Z");
    let mut broken = b"\xff\xfe\xed\xa0\x80 background \xc3\n".to_vec();
    broken.extend_from_slice(good.as_bytes());
    broken.extend_from_slice(b"\n\xe2\x82");
    v.push(
        Case::new(
            "bg-dosya",
            "bg",
            json!({"files": [path("work/yok"), path("work/p1"), "", path("work/bos"), path("work/bozuk"), path("work/link")],
                   "now": T, "tz": "UTC0"}),
        )
        .file(Fx::File("work/bos".into(), Vec::new(), 0o644))
        .file(Fx::File("work/bozuk".into(), broken, 0o644))
        .file(Fx::Link("work/link".into(), "bozuk".into())),
    );
    // kayıt 8 MiB kuyruğunun tamamen dışında / içinde (dönen satırlar karşılaştırılmasın diye yalnız karar)
    for (name, filler) in [
        ("disinda", 8 * 1024 * 1024usize),
        ("icinde", 8 * 1024 * 1024 - 4096),
    ] {
        let mut data = good.clone().into_bytes();
        data.push(b'\n');
        data.extend(std::iter::repeat_n(b'x', filler));
        v.push(
            Case::new(
                format!("bg-kuyruk-{name}"),
                "bg",
                json!({"files": [path("work/buyuk")], "now": T, "tz": "UTC0"}),
            )
            .file(Fx::File("work/buyuk".into(), data, 0o644)),
        );
    }
    v
}

pub fn run() {
    let mut r = Runner::new();
    let c = cases(&r.e);
    r.run(c, &[], rs_bg);
    r.finish("bg_work");
}
