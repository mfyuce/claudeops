//! Kancalara verilen [`copsd::Ctx::front`] canlıdır: gizli çalışırken yenilenince kanca yeni değeri görür (açılış kopyası
//! `front_secret` eski kalır). `harness = false`: süreç kendini copsd olarak yeniden başlatır, çünkü copsd bayrakları argv'den
//! okur. Geçici `$HOME`/durum dizini ve boş port.
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

const OUT: &str = "COPSD_CTX_PROBE_OUT";

struct Proc(Child);

impl Drop for Proc {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

/// Alt süreç: kanca, gördüğü canlı ve açılış değerlerini dosyaya yazar.
fn child(out: String) {
    let rt = tokio::runtime::Runtime::new().unwrap();
    rt.block_on(copsd::run_with_hooks(|ctx| async move {
        tokio::spawn(async move {
            loop {
                let line = format!(
                    "{}|{}",
                    ctx.front.current().unwrap_or_default(),
                    ctx.front_secret.clone().unwrap_or_default()
                );
                let tmp = format!("{out}.tmp");
                std::fs::write(&tmp, line).unwrap();
                std::fs::rename(&tmp, &out).unwrap();
                tokio::time::sleep(Duration::from_millis(20)).await;
            }
        });
        copsd::Hooks::default()
    }))
    .unwrap();
}

fn put(p: &Path, b: &str) {
    use std::os::unix::fs::PermissionsExt;
    let _ = std::fs::remove_file(p);
    std::fs::write(p, b).unwrap();
    std::fs::set_permissions(p, std::fs::Permissions::from_mode(0o600)).unwrap();
}

fn until(out: &Path, want: &str) {
    let t = Instant::now();
    loop {
        let got = std::fs::read_to_string(out).unwrap_or_default();
        if got == want {
            return;
        }
        assert!(
            t.elapsed() < Duration::from_secs(10),
            "beklenen {want:?}, görülen {got:?}"
        );
        std::thread::sleep(Duration::from_millis(20));
    }
}

fn main() {
    if let Ok(out) = std::env::var(OUT) {
        return child(out);
    }
    let dir = std::env::temp_dir().join(format!("copsd-ctx-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let (sec, out) = (dir.join("front.secret"), dir.join("probe"));
    put(&sec, "eski\n");
    let c = Command::new(std::env::current_exe().unwrap())
        .args(["--listen", "127.0.0.1:0", "--upstream", "127.0.0.1:9"])
        .arg("--state-dir")
        .arg(&dir)
        .env(OUT, &out)
        .env("HOME", &dir)
        .env_remove("CLAUDEOPS_DIR")
        .env_remove("CLAUDEOPS_FRONT_SECRET")
        .env_remove("COPSD_LISTEN")
        .env_remove("COPSD_UPSTREAM")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let _p = Proc(c);
    until(&out, "eski|eski");
    put(&sec, "yenilendi\n");
    until(&out, "yenilendi|eski");
    std::fs::remove_file(&sec).unwrap();
    until(&out, "|eski");
    drop(_p);
    let _ = std::fs::remove_dir_all(&dir);
    println!("test ctx_front_follows_secret_rotation ... ok");
}
