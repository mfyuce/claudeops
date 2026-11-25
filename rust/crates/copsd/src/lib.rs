//! copsd: OSS ön sunucu. D0 = saf vekil: `--listen` (varsayılan 127.0.0.1:8765) -> `--upstream` (Python iç port, varsayılan 127.0.0.1:18765).
//! Ön kapı gizlisi: `--secret-file` (varsayılan ~/.claude/claudeops/front.secret; 0600 değilse REDDEDİLİR) ya da `CLAUDEOPS_FRONT_SECRET`.
//! `--dist <py/webui/dist>`: /assets/* ve /favicon.svg diskten sunulur (yoksa Python'a aktarılır).
//! `--mounts-file` (varsayılan ~/.claude/claudeops/derbent/mounts.json): uygulama mount'ları (`/<id>/` -> yerel derbent loopback portu,
//! kimlik copsd'de). Dosya yoksa ya da 0600 değilse mount kapalı; 2 sn'de bir değişiklik yoklanır. web.token yoksa mount hiç açılmaz.
//! Ortam: `COPSD_LISTEN`, `COPSD_UPSTREAM` bayrakların yedeğidir.
//!
//! Kütüphane + ince ikili: `copsd` ikilisi [`run`]'ı çağırır. Başka bir ikili (ör. enterprise) [`run_with`] ile yerel uç
//! kimlik/yetki kancası ([`cops_proxy::gate::LocalAuth`]), [`run_with_hooks`] ile ek olarak vekillenen istek ön süzgeci
//! ([`cops_proxy::gate::ForwardFilter`]) takabilir; kanca yoksa davranış `copsd` ile aynıdır.
use std::future::Future;
use std::net::SocketAddr;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;

/// Kanca kurucusuna verilen, copsd'nin çözdüğü ayarlar.
pub struct Ctx {
    /// Python iç portu.
    pub upstream: SocketAddr,
    /// Ön kapı gizlisi (`X-Cops-Front`); yoksa `None`.
    pub front_secret: Option<String>,
}

/// Komut satırında `name` bayrağının değeri.
pub fn arg(name: &str) -> Option<String> {
    let a: Vec<String> = std::env::args().collect();
    a.iter()
        .position(|x| x == name)
        .and_then(|i| a.get(i + 1).cloned())
}

fn read_secret() -> Result<Option<String>, String> {
    if let Ok(s) = std::env::var("CLAUDEOPS_FRONT_SECRET") {
        if !s.is_empty() {
            return Ok(Some(s));
        }
    }
    let path = arg("--secret-file").unwrap_or_else(|| {
        format!(
            "{}/.claude/claudeops/front.secret",
            std::env::var("HOME").unwrap_or_default()
        )
    });
    match std::fs::metadata(&path) {
        Err(_) => Ok(None),
        Ok(m) => {
            if m.permissions().mode() & 0o077 != 0 {
                return Err(format!("{path}: izinler 0600 değil, reddedildi"));
            }
            let s = std::fs::read_to_string(&path).map_err(|e| format!("{path}: {e}"))?;
            Ok(Some(s.trim().to_string()).filter(|s| !s.is_empty()))
        }
    }
}

/// Takılabilir kancalar (hepsi isteğe bağlı; `Default` = hiçbiri: davranış `copsd` ile aynı).
#[derive(Default)]
pub struct Hooks {
    /// Yerel uç kimlik/yetki kancası.
    pub local_auth: Option<Arc<dyn cops_proxy::gate::LocalAuth>>,
    /// Python'a aktarılan istekler için kimlik bilgisi ön süzgeci.
    pub forward_filter: Option<Arc<dyn cops_proxy::gate::ForwardFilter>>,
}

/// `copsd` ikilisi: kanca yok.
pub async fn run() -> std::io::Result<()> {
    run_with_hooks(|_| async { Hooks::default() }).await
}

/// `hook`: dinlemeye başlamadan hemen önce bir kez çağrılır (`--once` kipinde çağrılmaz). `None` = kanca yok.
pub async fn run_with<F, Fut>(hook: F) -> std::io::Result<()>
where
    F: FnOnce(Ctx) -> Fut,
    Fut: Future<Output = Option<Arc<dyn cops_proxy::gate::LocalAuth>>>,
{
    run_with_hooks(|ctx| async move {
        Hooks {
            local_auth: hook(ctx).await,
            forward_filter: None,
        }
    })
    .await
}

/// [`run_with`] + vekillenen istek ön süzgeci. `hooks`: dinlemeye başlamadan hemen önce bir kez çağrılır (`--once` kipinde
/// çağrılmaz).
pub async fn run_with_hooks<F, Fut>(hooks: F) -> std::io::Result<()>
where
    F: FnOnce(Ctx) -> Fut,
    Fut: Future<Output = Hooks>,
{
    let listen: SocketAddr = arg("--listen")
        .or_else(|| std::env::var("COPSD_LISTEN").ok())
        .unwrap_or_else(|| "127.0.0.1:8765".into())
        .parse()
        .expect("--listen");
    let up: SocketAddr = arg("--upstream")
        .or_else(|| std::env::var("COPSD_UPSTREAM").ok())
        .unwrap_or_else(|| "127.0.0.1:18765".into())
        .parse()
        .expect("--upstream");
    let secret = match read_secret() {
        Ok(s) => s,
        Err(e) => {
            eprintln!("copsd: {e}");
            std::process::exit(2);
        }
    };
    let front_secret = secret.clone().unwrap_or_default();
    eprintln!(
        "copsd: {listen} -> {up} (gizli: {})",
        if secret.is_some() {
            "var"
        } else {
            "YOK, X-Forwarded-For güvenilmez"
        }
    );
    let proxy = match secret {
        Some(sec) => cops_proxy::Proxy::with_secret(up, &sec),
        None => cops_proxy::Proxy::new(up),
    };
    let proxy = match arg("--dist") {
        Some(d) => proxy.with_dist(std::path::PathBuf::from(d)),
        None => proxy,
    };
    // Yerel uçlar (Aşama 1): token dosyası ve DB yoksa uç AÇILMAZ (istek Python'a gider). Token dosyası 0600 olmalı (ön kapı gizlisiyle aynı kural).
    let home = std::env::var("HOME").unwrap_or_default();
    let tok_path = std::path::PathBuf::from(
        arg("--token-file").unwrap_or_else(|| format!("{home}/.claude/claudeops/web.token")),
    );
    let db_path = std::path::PathBuf::from(
        arg("--db").unwrap_or_else(|| format!("{home}/.claude/claudeops/claudeops.db")),
    );
    let proxy = match std::fs::metadata(&tok_path) {
        Ok(m) if m.permissions().mode() & 0o077 == 0 && db_path.exists() => {
            let t = cops_auth::Token::from_file(&tok_path);
            if t.is_empty() {
                proxy
            } else {
                eprintln!("copsd: yerel uç açık: GET /api/steward/questions");
                proxy.with_local(cops_proxy::LocalCfg {
                    token: t,
                    db: db_path.clone(),
                })
            }
        }
        _ => proxy,
    };
    // Metrik deposu (cops-metrics): `--metrics-db` (varsayılan ~/.claude/claudeops/metrics.db). Uçlar: POST /api/metrics/points
    // (web.token ya da loopback + ön kapı gizlisi), GET /api/metrics/series|names (web.token). Token yoksa uçlar AÇILMAZ (Python'a gider).
    let mdb = std::path::PathBuf::from(
        arg("--metrics-db").unwrap_or_else(|| format!("{home}/.claude/claudeops/metrics.db")),
    );
    let store = match cops_metrics::Store::open(&mdb) {
        Ok(s) => Some(std::sync::Arc::new(s)),
        Err(e) => {
            eprintln!("copsd: metrik deposu açılamadı: {e}");
            None
        }
    };
    let instances = std::path::PathBuf::from(
        arg("--instances").unwrap_or_else(|| format!("{home}/.claude/claudeops/instances.json")),
    );
    // Günlük proje ilerleme işi (model YOK). `--once`: bir kez koş ve çık (elle/sınama). Aksi halde açılışta son nokta 20 saatten eskiyse koşar, sonra saatte bir bakar.
    if let Some(st) = store.clone() {
        let (db, inst) = (db_path.clone(), instances.clone());
        let tick = move || -> Result<(usize, usize), String> {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs_f64())
                .unwrap_or(0.0);
            let last = st.last_ts("job.project_progress", "ms")?.unwrap_or(0.0);
            if now - last < 20.0 * 3600.0 && !std::env::args().any(|a| a == "--once") {
                return Ok((0, 0));
            }
            cops_progress::run(&st, &db, &inst, now)
        };
        if std::env::args().any(|a| a == "--once") {
            match tick() {
                Ok((p, n)) => println!("project-progress: {p} proje, {n} nokta"),
                Err(e) => {
                    eprintln!("project-progress: {e}");
                    std::process::exit(1);
                }
            }
            return Ok(());
        }
        tokio::spawn(async move {
            loop {
                let t = tick.clone();
                match tokio::task::spawn_blocking(t).await {
                    Ok(Ok((p, n))) if p > 0 => {
                        eprintln!("copsd: proje ilerleme: {p} proje, {n} nokta")
                    }
                    Ok(Err(e)) => eprintln!("copsd: proje ilerleme hatası: {e}"),
                    _ => {}
                }
                tokio::time::sleep(std::time::Duration::from_secs(3600)).await;
            }
        });
    }
    let proxy = match (store, std::fs::metadata(&tok_path)) {
        (Some(store), Ok(m)) if m.permissions().mode() & 0o077 == 0 => {
            let t = cops_auth::Token::from_file(&tok_path);
            if t.is_empty() {
                proxy
            } else {
                eprintln!("copsd: metrik uçları açık: /api/metrics/points|series|names");
                proxy.with_metrics(cops_proxy::MetricsCfg {
                    store,
                    token: t,
                    front_secret: cops_auth::Token::new(&front_secret),
                })
            }
        }
        _ => proxy,
    };
    // Uygulama mount'ları: kimlik web.token (0600) + `cops_ext` çerezi; token yoksa mount AÇILMAZ (istek Python'a gider).
    let mounts_file = std::path::PathBuf::from(
        arg("--mounts-file")
            .unwrap_or_else(|| format!("{home}/.claude/claudeops/derbent/mounts.json")),
    );
    let proxy = match std::fs::metadata(&tok_path) {
        Ok(m)
            if m.permissions().mode() & 0o077 == 0
                && !cops_auth::Token::from_file(&tok_path).is_empty() =>
        {
            let mounts = cops_proxy::mount::Mounts::with_db(
                mounts_file.clone(),
                db_path.exists().then(|| db_path.clone()),
            );
            match mounts.refresh() {
                Some(line) => eprintln!("copsd: {line}"),
                None => eprintln!(
                    "copsd: mount kapalı: {} yok (2 sn'de bir yoklanır)",
                    mounts_file.display()
                ),
            }
            mounts.spawn_watch(std::time::Duration::from_secs(2));
            proxy.with_mounts(cops_proxy::MountCfg {
                mounts,
                token: cops_auth::Token::from_file(&tok_path),
            })
        }
        _ => {
            eprintln!("copsd: mount kapalı: web.token yok ya da 0600 değil");
            proxy
        }
    };
    let h = hooks(Ctx {
        upstream: up,
        front_secret: Some(front_secret).filter(|s| !s.is_empty()),
    })
    .await;
    let proxy = match h.local_auth {
        Some(h) => proxy.with_local_auth(h),
        None => proxy,
    };
    let proxy = match h.forward_filter {
        Some(f) => proxy.with_forward_filter(f),
        None => proxy,
    };
    cops_proxy::serve(listen, proxy).await
}
