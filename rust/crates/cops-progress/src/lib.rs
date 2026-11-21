//! Günlük proje ilerleme taraması (deterministik, model çağrısı YOK). Projeler: değnekçi projeleri (`claudeops.db` docs
//! `steward/projects` + `steward/stewards/*/projects`, yalnız yerel = `host` boş) -> roster (`instances.json`) `blueprint` eşlemesiyle `cwd`;
//! roster'da olup değnekçide olmayan `cwd`ler de blueprint adıyla eklenir. AYNI `cwd` TEK KEZ sayılır (copsdev/copsdevderbent aynı TODO.md).
//! Uzak hostlar (host != '') BU SÜRÜMDE yok (TODO: host API'siyle).
//! Seriler (key = proje): project.todo_open ([ ] ve [~]), project.todo_done ([x]), project.tbd_open, project.done_lines (DONE.md `- ` satırı,
//! ayrı seri: bazı projeler biten maddeyi TODO'dan silip DONE.md'ye taşır), project.commits_24h. Faz `meta.phase`.

use cops_metrics::Point;
use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::process::Command;

#[derive(Debug, PartialEq, Default, Clone)]
pub struct Counts {
    pub todo_open: u32,
    pub todo_done: u32,
    pub tbd_open: u32,
    pub done_lines: u32,
}

/// `- [ ]`, `* [~]` açık; `- [x]` biten (girinti serbest).
pub fn count_todo(text: &str) -> (u32, u32) {
    let (mut open, mut done) = (0, 0);
    for l in text.lines() {
        let t = l.trim_start();
        let Some(rest) = t.strip_prefix("- [").or_else(|| t.strip_prefix("* [")) else { continue };
        match rest.as_bytes() {
            [b' ' | b'~', b']', ..] => open += 1,
            [b'x' | b'X', b']', ..] => done += 1,
            _ => {}
        }
    }
    (open, done)
}

/// TOBEDECIDED.md: `## Açık` bölümü varsa o bölümdeki (sonraki `## ` başlığına dek) `###`+ başlıklar; yoksa büyük harfli `AÇIK` geçen başlıklar.
pub fn count_tbd_open(text: &str) -> u32 {
    let is_h2 = |l: &str| l.starts_with("## ");
    if let Some(start) = text.lines().position(|l| is_h2(l) && l.trim_start_matches('#').trim().to_lowercase().starts_with("açık")) {
        return text.lines().skip(start + 1).take_while(|l| !is_h2(l)).filter(|l| l.starts_with("###")).count() as u32;
    }
    text.lines().filter(|l| l.starts_with('#') && l.contains("AÇIK")).count() as u32
}

pub fn count_done_lines(text: &str) -> u32 {
    text.lines().filter(|l| l.starts_with("- ")).count() as u32
}

pub fn count_dir(dir: &Path) -> Counts {
    let rd = |n: &str| std::fs::read_to_string(dir.join(n)).unwrap_or_default();
    let (todo_open, todo_done) = count_todo(&rd("TODO.md"));
    Counts { todo_open, todo_done, tbd_open: count_tbd_open(&rd("TOBEDECIDED.md")), done_lines: count_done_lines(&rd("DONE.md")) }
}

pub fn commits_24h(dir: &Path) -> Option<u32> {
    let o = Command::new("git").arg("-C").arg(dir).args(["log", "--since=24 hours ago", "--oneline"]).output().ok()?;
    o.status.success().then(|| String::from_utf8_lossy(&o.stdout).lines().count() as u32)
}

#[derive(Debug, Clone)]
pub struct Project {
    pub name: String,
    pub cwd: PathBuf,
    pub phase: String,
}

/// `claudeops.db` (salt okunur) + `instances.json` -> yerel projeler (cwd tekilleştirilmiş, ad sırasıyla ilk).
pub fn discover(db: &Path, instances: &Path) -> Vec<Project> {
    let mut phases: BTreeMap<String, String> = BTreeMap::new();
    if let Ok(c) = Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX) {
        if let Ok(mut st) = c.prepare("SELECT body FROM docs WHERE name='steward/projects' OR (name LIKE 'steward/stewards/%/projects')") {
            let bodies: Vec<String> = st.query_map([], |r| r.get::<_, String>(0)).map(|i| i.filter_map(|x| x.ok()).collect()).unwrap_or_default();
            for b in bodies {
                if let Ok(Value::Object(m)) = serde_json::from_str::<Value>(&b) {
                    for (k, v) in m {
                        if v.get("host").and_then(|h| h.as_str()).unwrap_or("").is_empty() {
                            phases.entry(k).or_insert_with(|| v.get("phase").and_then(|p| p.as_str()).unwrap_or("").to_string());
                        }
                    }
                }
            }
        }
    }
    let inst: Value = std::fs::read_to_string(instances).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(Value::Null);
    let mut cwd_of: BTreeMap<String, String> = BTreeMap::new(); // blueprint -> cwd
    if let Some(Value::Object(m)) = inst.get("instances") {
        for (_, v) in m {
            if let (Some(bp), Some(cwd)) = (v.get("blueprint").and_then(|x| x.as_str()), v.get("cwd").and_then(|x| x.as_str())) {
                cwd_of.entry(bp.to_string()).or_insert_with(|| cwd.to_string());
            }
        }
    }
    let mut by_cwd: BTreeMap<PathBuf, Project> = BTreeMap::new();
    let mut add = |name: &str, cwd: &str, phase: &str| {
        let p = PathBuf::from(cwd);
        let key = p.canonicalize().unwrap_or(p.clone());
        by_cwd.entry(key).or_insert_with(|| Project { name: name.to_string(), cwd: p, phase: phase.to_string() });
    };
    for (name, phase) in &phases {
        if let Some(cwd) = cwd_of.get(name) {
            add(name, cwd, phase);
        }
    }
    for (bp, cwd) in &cwd_of {
        add(bp, cwd, "");
    }
    let all: Vec<Project> = by_cwd.into_values().filter(|p| p.cwd.is_dir()).collect();
    // Worktree projesi: TODO.md başka bir projenin klasöründeki dosyaya symlink ise (scripts/worktree-docs-link.sh) aynı dosya iki kez
    // sayılmasın: sahibi (gerçek dosyanın klasörü olan proje) kalır, symlink'li olan atlanır.
    let canon = |p: &Path| p.canonicalize().unwrap_or_else(|_| p.to_path_buf());
    let homes: Vec<PathBuf> = all.iter().map(|p| canon(&p.cwd)).collect();
    all.into_iter()
        .zip(homes.clone())
        .filter(|(p, home)| match canon(&p.cwd.join("TODO.md")).parent() {
            Some(par) if par != home.as_path() => !homes.iter().any(|h| h.as_path() == par),
            _ => true,
        })
        .map(|(p, _)| p)
        .collect()
}

/// Bir projenin noktaları (5 seri).
pub fn points_for(p: &Project, ts: f64) -> Vec<Point> {
    let c = count_dir(&p.cwd);
    let mk = |name: &str, v: f64| Point { name: name.into(), key: p.name.clone(), owner: String::new(), unit: "adet".into(), ts, value: v, meta: Some(json!({"phase": p.phase}).to_string()) };
    let mut v = vec![mk("project.todo_open", c.todo_open as f64), mk("project.todo_done", c.todo_done as f64), mk("project.tbd_open", c.tbd_open as f64), mk("project.done_lines", c.done_lines as f64)];
    if let Some(n) = commits_24h(&p.cwd) {
        v.push(mk("project.commits_24h", n as f64));
    }
    v
}

/// Tam tarama: tüm projeler + işin kendi metriği (`job.project_progress`: süre ms, proje sayısı meta'da). Dönüş (proje sayısı, nokta sayısı).
pub fn run(store: &cops_metrics::Store, db: &Path, instances: &Path, now: f64) -> Result<(usize, usize), String> {
    let t0 = std::time::Instant::now();
    let projects = discover(db, instances);
    let mut pts: Vec<Point> = projects.iter().flat_map(|p| points_for(p, now)).collect();
    pts.push(Point { name: "job.project_progress".into(), key: "ms".into(), owner: String::new(), unit: "ms".into(), ts: now, value: t0.elapsed().as_secs_f64() * 1000.0, meta: Some(json!({"projects": projects.len(), "ok": true}).to_string()) });
    let n = store.insert(&pts)?;
    Ok((projects.len(), n))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn todo_counts() {
        let t = "- [ ] a\n  - [~] b\n- [x] c\n* [X] d\n- [?] e\ntext - [ ] no\n";
        assert_eq!(count_todo(t), (2, 2));
    }

    #[test]
    fn tbd_counts() {
        let a = "# t\n\n## Açık\n\n### 1) **AÇIK** x\n### 2) y\n\n## Kapalı\n### 3) z\n";
        assert_eq!(count_tbd_open(a), 2);
        assert_eq!(count_tbd_open("# t\n## TBD#1 AÇIK soru\n## TBD#2 [KAPANDI]\n"), 1);
        assert_eq!(count_tbd_open(""), 0);
    }

    #[test]
    fn done_lines_separate() {
        assert_eq!(count_done_lines("## g\n- a\n- b\ntext\n"), 2);
    }

    #[test]
    fn symlinked_todo_worktree_is_skipped() {
        let d = tempfile::tempdir().unwrap();
        let (main, wt) = (d.path().join("main"), d.path().join("wt"));
        std::fs::create_dir(&main).unwrap();
        std::fs::create_dir(&wt).unwrap();
        std::fs::write(main.join("TODO.md"), "- [ ] a\n").unwrap();
        std::os::unix::fs::symlink(main.join("TODO.md"), wt.join("TODO.md")).unwrap();
        let inst = d.path().join("i.json");
        std::fs::write(&inst, format!(r#"{{"instances":{{"a":{{"blueprint":"cops","cwd":"{}"}},"b":{{"blueprint":"copsdevderbent","cwd":"{}"}}}}}}"#, main.display(), wt.display())).unwrap();
        let ps = discover(&d.path().join("none.db"), &inst);
        assert_eq!(ps.iter().map(|p| p.name.as_str()).collect::<Vec<_>>(), vec!["cops"]);
    }

    #[test]
    fn discover_dedupes_shared_cwd_and_run_writes() {
        let d = tempfile::tempdir().unwrap();
        let proj = d.path().join("p");
        std::fs::create_dir(&proj).unwrap();
        std::fs::write(proj.join("TODO.md"), "- [ ] a\n- [x] b\n").unwrap();
        std::fs::write(proj.join("DONE.md"), "- x\n").unwrap();
        let inst = d.path().join("instances.json");
        let c = proj.display();
        std::fs::write(&inst, format!(r#"{{"instances":{{"a1":{{"blueprint":"copsdev","cwd":"{c}"}},"a2":{{"blueprint":"copsdevderbent","cwd":"{c}"}}}}}}"#)).unwrap();
        let db = d.path().join("c.db");
        let conn = Connection::open(&db).unwrap();
        conn.execute("CREATE TABLE docs(name TEXT PRIMARY KEY, body TEXT)", []).unwrap();
        conn.execute("INSERT INTO docs VALUES('steward/projects', ?1)", [r#"{"copsdev":{"phase":"active","host":""},"uzak":{"phase":"active","host":"ulak_31"}}"#]).unwrap();
        let ps = discover(&db, &inst);
        assert_eq!(ps.len(), 1);
        assert_eq!(ps[0].name, "copsdev");
        assert_eq!(ps[0].phase, "active");
        let st = cops_metrics::Store::open(&d.path().join("m.db")).unwrap();
        let (n, _) = run(&st, &db, &inst, 100.0).unwrap();
        assert_eq!(n, 1);
        let r = st.series("project.todo_open", Some("copsdev"), "", 0.0, 1e9, 10).unwrap();
        assert_eq!(r["series"][0]["points"][0]["value"], 1.0);
        assert_eq!(st.series("project.done_lines", Some("copsdev"), "", 0.0, 1e9, 10).unwrap()["series"][0]["points"][0]["value"], 1.0);
        assert!(st.names("").unwrap().to_string().contains("job.project_progress"));
    }
}
