//! G8: tanıtıcı ve süreç sızıntısı. TEK test (ayrı test ikilisi): sayımı başka iş parçacığı bozmasın.

#[path = "g8/support.rs"]
mod support;

use cops_providers::approval::NewRun;
use cops_providers::real::approval::ApprovalStore;
use cops_providers::real::diaglog::DiagLog;
use cops_providers::real::effects;
use cops_providers::real::help::HelpCache;
use cops_providers::real::lock::FileLock;
use cops_providers::real::oneshot::{ChatRequest, OneShot};
use cops_providers::real::process::{self, Capture, Spec};
use cops_providers::{Effect, LiveProbe, ModelCatalog, Probe, Providers, Settings};
use std::fs;
use std::sync::Arc;
use std::time::Duration;
use support::{mkfifo, Tmp};

fn open_fds() -> usize {
    fs::read_dir("/proc/self/fd").unwrap().count()
}

/// Bu sürecin (herhangi bir iş parçacığının) hâlâ duran ya da beklenmemiş çocukları.
fn children() -> Vec<String> {
    let own = std::process::id().to_string();
    fs::read_dir("/proc")
        .unwrap()
        .flatten()
        .filter_map(|e| fs::read_to_string(e.path().join("stat")).ok())
        .filter(|s| {
            s.rsplit(')')
                .next()
                .and_then(|r| r.split_whitespace().nth(1))
                == Some(own.as_str())
        })
        .collect()
}

#[test]
fn a_hundred_rounds_of_failures_leak_no_descriptor_and_no_child() {
    let t = Tmp::new();
    let slow = t.script("bin/slow", "sleep 30 & sleep 30");
    let loud = t.script("bin/loud", "yes");
    let ok = t.script("bin/ok", "echo --flag");
    let fifo = t.path("work/boru");
    mkfifo(&fifo);
    let file = t.write("work/f", "x", 0o600);
    let env = t.env(&[]);
    let probe = t.probe_with(
        env.clone(),
        Arc::new(HelpCache::with_timeout(Duration::from_millis(20))),
    );
    let paths = t.paths();
    let (settings, catalog) = (Settings::default(), ModelCatalog::default());
    let providers = Providers {
        settings: &settings,
        catalog: &catalog,
        paths: &paths,
        probe: &probe,
    };
    let approvals = ApprovalStore::new(&paths);
    let diag = DiagLog::new(t.path("state/diag.log"));
    let work = t.path("work");
    let argv = vec!["a".to_string()];
    let run = NewRun {
        cwd: &work,
        session: "s",
        argv_resume: &argv,
        owner: "",
    };
    let round = || {
        for (bin, ms) in [(&slow, 15), (&loud, 2000), (&ok, 2000), (&file, 50)] {
            let argv = vec![bin.clone()];
            let spec = Spec {
                argv: &argv,
                cwd: None,
                env: &env,
                timeout: Duration::from_millis(ms),
                stdout: Capture::Bounded(1024),
                stderr: Capture::Bounded(1024),
            };
            let _ = process::run(&spec);
        }
        let _ = probe.claude_help(&slow);
        let _ = probe.register_mcp(
            &t.path("work"),
            &t.path("work/yok"),
            std::slice::from_ref(&ok),
        );
        assert!(probe.read_bytes(&fifo, 10).is_none());
        assert!(probe.read_tail(&file, 10).is_some());
        let _ = probe.list_dir(&t.path("work"));
        let _ = probe.sqlite_cell(&file, "SELECT ?", "x");
        assert!(effects::apply(&Effect::WriteSecret {
            path: fifo.clone(),
            content: "s".into()
        })
        .is_err());
        effects::apply(&Effect::WriteAtomic {
            path: t.path("work/a"),
            content: "s".into(),
        })
        .unwrap();
        let held = FileLock::acquire(&file, "/", Duration::from_millis(5)).unwrap();
        assert!(FileLock::acquire(&file, "/", Duration::from_millis(5)).is_err());
        drop(held);
        let _ = probe.issue_agent_token("s1");
        // G10: onay kaydı ve tek atımlık çağrının hata yolları
        assert!(approvals.register("BOZUK AD", run).is_err());
        approvals.register("r1", run).unwrap();
        assert!(approvals.register("r1", run).is_err());
        assert!(approvals.set_state("r1", "done").unwrap());
        let shot = OneShot {
            providers: &providers,
            env: &env,
            approvals: &approvals,
            diag: &diag,
        };
        for (bin, secs) in [(&slow, 0.015), (&ok, 2.0), (&file, 0.05), (&fifo, 0.05)] {
            let mut req = ChatRequest::new(&work, "p");
            req.binary = Some(bin);
            req.timeout = secs;
            assert!(shot.chat_once(&req).is_err());
            let _ = shot.run_argv("x", std::slice::from_ref(bin), &work, secs);
        }
    };
    round(); // tembel açılan kalıcı tanıtıcılar sayıma girmesin
    let before = open_fds();
    for _ in 0..100 {
        round();
    }
    assert_eq!(open_fds(), before);
    assert_eq!(children(), Vec::<String>::new());
}
