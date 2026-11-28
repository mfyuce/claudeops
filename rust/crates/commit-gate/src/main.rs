//! `commit-gate`: git kancaları (`commit-msg`, `pre-push`), kurulum ve `cops check` için denetim.
use commit_gate::{evaluate, parse_numstat, FileStat, Verdict};
use std::io::BufRead;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};

const MARK: &str = "# claudeops-commit-gate";
const HOOKS: [&str; 2] = ["commit-msg", "pre-push"];
const USAGE: &str =
    "kullanım: commit-gate commit-msg --tbd DOSYA MESAJ | pre-push --tbd DOSYA [uzak url] | \
install --tbd DOSYA --repo DİZİN... | check --core DİZİN";

fn git(repo: Option<&Path>, args: &[&str]) -> Result<String, String> {
    git_cfg(repo, &[], args)
}

/// `cfg`: alt komuttan önce `-c` ile verilen ayarlar.
fn git_cfg(repo: Option<&Path>, cfg: &[String], args: &[&str]) -> Result<String, String> {
    let mut c = Command::new("git");
    if let Some(r) = repo {
        // başka repoya bakarken kancadan miras kalan GIT_* değişkenleri hedefi değiştirmesin
        c.arg("-C").arg(r);
        for k in [
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_COMMON_DIR",
        ] {
            c.env_remove(k);
        }
    }
    c.args(["-c", "core.quotePath=false"]);
    for kv in cfg {
        c.arg("-c").arg(kv);
    }
    c.args(args);
    let out = c.output().map_err(|e| format!("git çalışmadı: {e}"))?;
    if !out.status.success() {
        return Err(format!(
            "git {}: {}",
            args.join(" "),
            String::from_utf8_lossy(&out.stderr).trim()
        ));
    }
    Ok(String::from_utf8_lossy(&out.stdout).into_owned())
}

const DIFF_FMT: [&str; 4] = [
    "--no-color",
    "--no-ext-diff",
    "--src-prefix=a/",
    "--dst-prefix=b/",
];

/// git'in yerleşik hunk başlığı kuralı (kapsayan en yakın satır harf, `_` ya da `$` ile başlar = girintisiz).
const DEFAULT_FUNCNAME: &str = "^[[:alpha:]$_].*$";

/// `.gitattributes` dosyalara bir diff sürücüsü atadıysa (`diff=python` ya da özel ad) o sürücünün hunk başlığı kuralını
/// varsayılana çevirir: `new_public` başlığı "kapsayan girintisiz satır" sayar (`a2c21d85`). Çalışma ağacı ve dizindeki
/// öznitelikler birlikte sorulur.
fn funcname_overrides(repo: Option<&Path>, files: &[FileStat]) -> Result<Vec<String>, String> {
    let paths: Vec<&str> = files.iter().map(|f| f.path.as_str()).collect();
    if paths.is_empty() {
        return Ok(Vec::new());
    }
    let mut names: Vec<String> = Vec::new();
    for cached in [false, true] {
        let mut a = vec!["check-attr", "-z"];
        if cached {
            a.push("--cached");
        }
        a.extend(["diff", "--"]);
        a.extend(&paths);
        let out = git(repo, &a)?;
        // `yol\0diff\0değer\0` üçlüleri
        for v in out
            .split('\0')
            .collect::<Vec<_>>()
            .chunks(3)
            .filter_map(|c| c.get(2))
        {
            if !matches!(*v, "" | "unspecified" | "set" | "unset") && !names.iter().any(|n| n == v)
            {
                names.push(v.to_string());
            }
        }
    }
    Ok(names
        .into_iter()
        .map(|n| format!("diff.{n}.xfuncname={DEFAULT_FUNCNAME}"))
        .collect())
}

fn staged_verdict(msg: &str, tbd: Option<&str>) -> Result<Verdict, String> {
    let stat = parse_numstat(&git(None, &["diff", "--cached", "--numstat", "-z", "-M"])?);
    let mut args = vec!["diff", "--cached", "-U0", "-M"];
    args.extend(DIFF_FMT);
    let cfg = funcname_overrides(None, &stat)?;
    Ok(evaluate(msg, &stat, &git_cfg(None, &cfg, &args)?, tbd))
}

fn commit_verdict(repo: Option<&Path>, sha: &str, tbd: Option<&str>) -> Result<Verdict, String> {
    let msg = git(repo, &["log", "-1", "--format=%B", sha])?;
    let base = ["diff-tree", "--root", "-r", "--no-commit-id", "-M"];
    let mut a = base.to_vec();
    a.extend(["--numstat", "-z", sha]);
    let stat = parse_numstat(&git(repo, &a)?);
    let mut b = base.to_vec();
    b.extend(["-p", "-U0"]);
    b.extend(DIFF_FMT);
    b.push(sha);
    let cfg = funcname_overrides(repo, &stat)?;
    Ok(evaluate(&msg, &stat, &git_cfg(repo, &cfg, &b)?, tbd))
}

fn report(prefix: &str, v: &Verdict) -> bool {
    for w in &v.warnings {
        eprintln!("commit-gate uyarı: {prefix}{w}");
    }
    for e in &v.errors {
        eprintln!("commit-gate RET: {prefix}{e}");
    }
    v.errors.is_empty()
}

fn commit_msg(tbd: Option<&str>, file: &str) -> Result<bool, String> {
    // birleştirme commit'inin içeriği zaten denetlenmiş commit'lerden gelir
    let merge = git(None, &["rev-parse", "--git-path", "MERGE_HEAD"])?;
    if Path::new(merge.trim()).exists() {
        return Ok(true);
    }
    let msg = std::fs::read_to_string(file).map_err(|e| format!("{file}: {e}"))?;
    Ok(report("", &staged_verdict(&msg, tbd)?))
}

fn commits(repo: Option<&Path>, args: &[&str]) -> Result<Vec<String>, String> {
    let mut a = vec!["rev-list", "--no-merges"];
    a.extend(args);
    Ok(git(repo, &a)?.lines().map(str::to_string).collect())
}

fn pre_push(tbd: Option<&str>) -> Result<bool, String> {
    let mut ok = true;
    for line in std::io::stdin().lock().lines() {
        let line = line.map_err(|e| e.to_string())?;
        let f: Vec<&str> = line.split_whitespace().collect();
        let [_, local, _, _] = f[..] else { continue };
        if local.bytes().all(|b| b == b'0') {
            continue; // dal silme
        }
        // yalnız hiçbir uzakta olmayan commit'ler: eski geçmiş geriye dönük reddedilmez
        for sha in commits(None, &[local, "--not", "--remotes"])? {
            ok &= report(&format!("{:.9}: ", sha), &commit_verdict(None, &sha, tbd)?);
        }
    }
    Ok(ok)
}

fn hooks_dir(repo: &Path) -> Result<PathBuf, String> {
    let p = PathBuf::from(git(Some(repo), &["rev-parse", "--git-path", "hooks"])?.trim());
    Ok(if p.is_absolute() { p } else { repo.join(p) })
}

fn quote(s: &str) -> String {
    format!("'{}'", s.replace('\'', "'\\''"))
}

fn install(tbd: &str, repos: &[String]) -> Result<bool, String> {
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    let exe = quote(&exe.to_string_lossy());
    for repo in repos {
        let dir = hooks_dir(Path::new(repo))?;
        // önce hepsini denetle: yabancı kanca varsa hiçbir şey yazma
        for h in HOOKS {
            let p = dir.join(h);
            if p.symlink_metadata().is_ok()
                && !std::fs::read_to_string(&p)
                    .unwrap_or_default()
                    .contains(MARK)
            {
                return Err(format!(
                    "{} başka bir kanca; üzerine yazılmadı",
                    p.display()
                ));
            }
        }
        std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
        for h in HOOKS {
            let p = dir.join(h);
            let body = format!(
                "#!/bin/sh\n{MARK}\nBIN={exe}\n[ -x \"$BIN\" ] || {{ echo \"commit-gate ikilisi yok: $BIN (scripts/commit-gate-install.sh)\" >&2; exit 1; }}\nexec \"$BIN\" {h} --tbd {} \"$@\"\n",
                quote(tbd)
            );
            std::fs::write(&p, body).map_err(|e| format!("{}: {e}", p.display()))?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o755))
                    .map_err(|e| e.to_string())?;
            }
            println!("kuruldu: {}", p.display());
        }
    }
    Ok(true)
}

/// Çekirdek ve yanındaki enterprise: kancalar kurulu mu, gönderilmemiş commit'ler kurala uyuyor mu.
fn check(core: &Path) -> Result<bool, String> {
    let mut repos = vec![core.to_path_buf()];
    if let Some(ent) = core
        .parent()
        .map(|p| p.join("claudeops-enterprise"))
        .filter(|p| p.join(".git").exists())
    {
        repos.push(ent);
    }
    // TOBEDECIDED.md ana checkout'ta (worktree'de yoksa ortak git dizininin üstü)
    let common = git(Some(core), &["rev-parse", "--git-common-dir"])?;
    let common = core.join(common.trim());
    let tbd = std::fs::read_to_string(core.join("TOBEDECIDED.md"))
        .or_else(|_| std::fs::read_to_string(common.join("../TOBEDECIDED.md")))
        .ok();
    let mut ok = true;
    for repo in &repos {
        let name = repo.display();
        let dir = hooks_dir(repo)?;
        for h in HOOKS {
            if !std::fs::read_to_string(dir.join(h))
                .unwrap_or_default()
                .contains(MARK)
            {
                eprintln!("commit-gate uyarı: {name}: {h} kancası kurulu değil (scripts/commit-gate-install.sh)");
                ok = false;
            }
        }
        for sha in commits(Some(repo), &["HEAD", "--not", "--remotes"])? {
            ok &= report(
                &format!("{name} {:.9}: ", sha),
                &commit_verdict(Some(repo), &sha, tbd.as_deref())?,
            );
        }
    }
    Ok(ok)
}

fn run(args: &[String]) -> Result<bool, String> {
    let (mut tbd, mut core, mut repos, mut rest) = (None, None, Vec::new(), Vec::new());
    let mut it = args.iter().skip(1);
    while let Some(a) = it.next() {
        let mut val = || it.next().cloned().ok_or_else(|| format!("{a} değer ister"));
        match a.as_str() {
            "--tbd" => tbd = Some(val()?),
            "--core" => core = Some(val()?),
            "--repo" => repos.push(val()?),
            _ => rest.push(a.clone()),
        }
    }
    let content = tbd.as_ref().and_then(|p| std::fs::read_to_string(p).ok());
    match args.first().map(String::as_str) {
        Some("commit-msg") => commit_msg(content.as_deref(), rest.first().ok_or(USAGE)?),
        Some("pre-push") => pre_push(content.as_deref()),
        Some("install") if !repos.is_empty() => install(tbd.as_deref().ok_or(USAGE)?, &repos),
        Some("check") => check(Path::new(core.as_deref().ok_or(USAGE)?)),
        _ => Err(USAGE.to_string()),
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match run(&args) {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => ExitCode::FAILURE,
        Err(e) => {
            eprintln!("commit-gate: {e}");
            ExitCode::from(2) // denetlenemedi: kanca yine durdurur (fail closed)
        }
    }
}
