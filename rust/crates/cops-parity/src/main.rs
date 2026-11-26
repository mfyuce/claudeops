//! cops-parity: istek listesini Python iç portuna ve Rust ön kapıya koşup JSON farkını raporlar.
use cops_parity::{config, exit_code, report, run, Target};
use std::net::SocketAddr;
use std::path::PathBuf;
use std::time::Duration;

const USAGE: &str = "cops-parity İSTEKLER.json [seçenekler]
  --python ADRES (127.0.0.1:28765)   --rust ADRES (127.0.0.1:8765)
  --token-file YOL (CLAUDEOPS_DIR ya da ~/.claude/claudeops altındaki web.token)   --no-token
  --timeout SANİYE (30)
  --only METİN        adında METİN geçen istekler
  --show-values       farklarda gövde değerlerini de yaz (sır içerebilir)
  --include-unsafe    yan etkisiz olduğu bilinmeyen istekleri de koş (her biri İKİ kez uygulanır)
  --allow-remote      loopback olmayan adrese de bağlan (token oraya gider)
Çıkış: 0 hepsi geçti, 1 fark/hata (ya da hiç istek koşmadı), 2 kullanım hatası.";

struct Opts {
    list: PathBuf,
    target: Target,
    only: Option<String>,
    values: bool,
    include_unsafe: bool,
}

fn default_token_file() -> PathBuf {
    match std::env::var("CLAUDEOPS_DIR") {
        Ok(d) if !d.is_empty() => PathBuf::from(d),
        _ => PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".claude/claudeops"),
    }
    .join("web.token")
}

fn parse(args: impl Iterator<Item = String>) -> Result<Opts, String> {
    let mut args = args;
    let (mut list, mut only, mut token_file) = (None, None, None);
    let (mut values, mut include_unsafe, mut allow_remote, mut no_token) =
        (false, false, false, false);
    let mut python: SocketAddr = SocketAddr::from(([127, 0, 0, 1], 28765));
    let mut rust: SocketAddr = SocketAddr::from(([127, 0, 0, 1], 8765));
    let mut timeout = 30u64;
    while let Some(a) = args.next() {
        let mut value = || args.next().ok_or_else(|| format!("{a}: değer gerekli"));
        match a.as_str() {
            "--python" => python = value()?.parse().map_err(|e| format!("--python: {e}"))?,
            "--rust" => rust = value()?.parse().map_err(|e| format!("--rust: {e}"))?,
            "--token-file" => token_file = Some(PathBuf::from(value()?)),
            "--timeout" => timeout = value()?.parse().map_err(|e| format!("--timeout: {e}"))?,
            "--only" => only = Some(value()?),
            "--no-token" => no_token = true,
            "--show-values" => values = true,
            "--include-unsafe" => include_unsafe = true,
            "--allow-remote" => allow_remote = true,
            s if !s.starts_with('-') && list.is_none() => list = Some(PathBuf::from(s)),
            s => return Err(format!("bilinmeyen argüman: {s}")),
        }
    }
    if !allow_remote
        && [python, rust]
            .iter()
            .any(|a| !a.ip().to_canonical().is_loopback())
    {
        return Err("loopback olmayan adres için --allow-remote gerekli".into());
    }
    let token = if no_token {
        None
    } else {
        let path = token_file.unwrap_or_else(default_token_file);
        let t = std::fs::read_to_string(&path)
            .map_err(|e| format!("{}: {e} (--no-token ile token'sız)", path.display()))?;
        Some(t.trim().to_string()).filter(|t| !t.is_empty())
    };
    Ok(Opts {
        list: list.ok_or("istek listesi gerekli")?,
        target: Target {
            python,
            rust,
            token,
            timeout: Duration::from_secs(timeout),
        },
        only,
        values,
        include_unsafe,
    })
}

#[tokio::main]
async fn main() {
    if std::env::args().any(|a| a == "--help" || a == "-h") {
        println!("{USAGE}");
        return;
    }
    let usage = |e: String| -> ! {
        eprintln!("cops-parity: {e}\n{USAGE}");
        std::process::exit(2);
    };
    let o = parse(std::env::args().skip(1)).unwrap_or_else(|e| usage(e));
    let text = std::fs::read_to_string(&o.list)
        .unwrap_or_else(|e| usage(format!("{}: {e}", o.list.display())));
    let mut cases = config::parse(&text).unwrap_or_else(|e| usage(e));
    if let Some(f) = &o.only {
        cases.retain(|c| c.name.contains(f.as_str()));
    }
    let outcomes = run(&cases, &o.target, o.include_unsafe).await;
    print!("{}", report(&outcomes, o.values));
    std::process::exit(exit_code(&outcomes));
}
