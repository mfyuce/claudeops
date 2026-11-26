//! copsd: OSS ön sunucu. D0 = saf vekil: `--listen` (varsayılan 127.0.0.1:8765) -> `--upstream` (Python iç port, varsayılan 127.0.0.1:18765).
//! Ön kapı gizlisi: `--secret-file` (varsayılan ~/.claude/claudeops/front.secret; 0600 değilse REDDEDİLİR) ya da `CLAUDEOPS_FRONT_SECRET`.
//! `--dist <py/webui/dist>`: /assets/* ve /favicon.svg diskten sunulur (yoksa Python'a aktarılır).
//! `--mounts-file` (varsayılan [`state_dir`]`/derbent/mounts.json`): uygulama mount'ları (`/<id>/` -> yerel derbent loopback portu,
//! kimlik copsd'de). Dosya yoksa ya da 0600 değilse mount kapalı; 2 sn'de bir değişiklik yoklanır. web.token yoksa mount hiç açılmaz.
//! `web.token` açılışta yalnız uçları açmak için denetlenir; değeri her istekte dosyadan okunur (silme/döndürme anında geçerli).
//! `--token-file` verilmezse `web.token` durum dizininden okunur ([`state_dir`]: `--state-dir`, `CLAUDEOPS_DIR`, `~/.claude/claudeops`).
//! Ortam: `COPSD_LISTEN`, `COPSD_UPSTREAM` bayrakların yedeğidir.
//! `--force-proxy-file` (varsayılan [`state_dir`]`/front_force_proxy`): listedeki yol önekleri Rust'ta karşılığı olsa bile
//! Python'a aktarılır ([`cops_proxy::force`]); açılışta ve SIGHUP'ta okunur. `GET /api/front/stats`: uç başına yerel/aktarım
//! sayaçları. Çekirdek yerel uçları [`routes::register`]de kaydedilir.
//!
//! Kütüphane + ince ikili: `copsd` ikilisi [`run`]'ı çağırır. Başka bir ikili (ör. enterprise) [`run_with`] ile yerel uç
//! kimlik/yetki kancası ([`cops_proxy::gate::LocalAuth`]), [`run_with_hooks`] ile ek olarak vekillenen istek ön süzgeci
//! ([`cops_proxy::gate::ForwardFilter`]) ve Rust'ın kendisinin cevapladığı uçlar ([`cops_proxy::gate::RouteHook`], ör. enterprise
//! `/api/auth/*`) takabilir; kanca yoksa davranış `copsd` ile aynıdır.
pub mod routes;

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

/// Durum dizini: `--state-dir`, yoksa `CLAUDEOPS_DIR` (boş değilse), yoksa `$HOME/.claude/claudeops` (Python
/// `paths.CLAUDEOPS_DIR` ile aynı kural; enterprise `copsd-ent` de bunu kullanır).
pub fn state_dir() -> std::path::PathBuf {
    if let Some(d) = arg("--state-dir") {
        return d.into();
    }
    match std::env::var("CLAUDEOPS_DIR") {
        Ok(d) if !d.is_empty() => d.into(),
        _ => format!(
            "{}/.claude/claudeops",
            std::env::var("HOME").unwrap_or_default()
        )
        .into(),
    }
}

/// `flag` verildiyse o yol, yoksa [`state_dir`] altındaki `name`.
fn state_path(flag: &str, name: &str) -> std::path::PathBuf {
    arg(flag)
        .map(Into::into)
        .unwrap_or_else(|| state_dir().join(name))
}

/// `web.token` yolu: `--token-file`, yoksa [`state_dir`]`/web.token` (R1-10: Python token'ı durum dizininden okur; yalnız
/// `$HOME` kullanmak durum dizini farklıyken ikinci bir acil token kabul ettiriyordu).
pub fn token_file() -> std::path::PathBuf {
    state_path("--token-file", "web.token")
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

fn log_force(f: &cops_proxy::force::ForceProxy) {
    let list = f.list();
    if !list.is_empty() {
        eprintln!(
            "copsd: force_proxy ({}): {} önek Python'a: {}",
            f.path().display(),
            list.len(),
            list.join(" ")
        );
    }
}

/// SIGHUP -> `force_proxy` dosyası yeniden okunur. İşleyici bu işlev döndüğünde KURULUDUR.
fn watch_sighup(f: Arc<cops_proxy::force::ForceProxy>) -> std::io::Result<()> {
    use tokio::signal::unix::{signal, SignalKind};
    let mut hup = signal(SignalKind::hangup())?;
    tokio::spawn(async move {
        while hup.recv().await.is_some() {
            match f.reload() {
                Ok(n) => {
                    eprintln!("copsd: SIGHUP: force_proxy yeniden okundu ({n} önek)");
                    log_force(&f);
                }
                Err(e) => eprintln!(
                    "copsd: SIGHUP: force_proxy okunamadı, eski liste geçerli: {}: {e}",
                    f.path().display()
                ),
            }
        }
    });
    Ok(())
}

/// Takılabilir kancalar (hepsi isteğe bağlı; `Default` = hiçbiri: davranış `copsd` ile aynı).
#[derive(Default)]
pub struct Hooks {
    /// Yerel uç kimlik/yetki kancası.
    pub local_auth: Option<Arc<dyn cops_proxy::gate::LocalAuth>>,
    /// Python'a aktarılan istekler için kimlik bilgisi ön süzgeci.
    pub forward_filter: Option<Arc<dyn cops_proxy::gate::ForwardFilter>>,
    /// Rust'ın kendisinin cevapladığı uçlar (enterprise `/api/auth/*`); üstlenmediği istek bugünkü gibi.
    pub routes: Option<Arc<dyn cops_proxy::gate::RouteHook>>,
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
            routes: None,
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
    // SIGHUP işleyicisi HEMEN kurulur (varsayılan davranış süreci öldürür; kancaların kurulumu saniyeler sürebilir).
    let force = Arc::new(cops_proxy::force::ForceProxy::load(state_path(
        "--force-proxy-file",
        "front_force_proxy",
    )));
    log_force(&force);
    watch_sighup(force.clone())?;
    let proxy = proxy
        .with_force_proxy(force)
        .with_stats(cops_proxy::StatsCfg {
            token: cops_auth::Token::from_file(&token_file()),
            front_secret: cops_auth::Token::new(&front_secret),
        });
    // Yerel uçlar (Aşama 1): token dosyası ve DB yoksa uç AÇILMAZ (istek Python'a gider). Token dosyası 0600 olmalı (ön kapı gizlisiyle aynı kural).
    let tok_path = token_file();
    let db_path = state_path("--db", "claudeops.db");
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
    // Metrik deposu (cops-metrics): `--metrics-db` (varsayılan [`state_dir`]`/metrics.db`). Uçlar: POST /api/metrics/points
    // (web.token ya da loopback + ön kapı gizlisi), GET /api/metrics/series|names (web.token). Token yoksa uçlar AÇILMAZ (Python'a gider).
    let mdb = state_path("--metrics-db", "metrics.db");
    let store = match cops_metrics::Store::open(&mdb) {
        Ok(s) => Some(std::sync::Arc::new(s)),
        Err(e) => {
            eprintln!("copsd: metrik deposu açılamadı: {e}");
            None
        }
    };
    let instances = state_path("--instances", "instances.json");
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
    let mounts_file = state_path("--mounts-file", "derbent/mounts.json");
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
    // Çoklu rota tablosu: panel kimlikli kayıtlar web.token ister; yoksa tablo AÇILMAZ (istek Python'a gider).
    let mut table = cops_proxy::routes::RouteTable::new();
    routes::register(
        &mut table,
        &routes::RouteCtx {
            state_dir: state_dir(),
            db: db_path.clone(),
            instances: instances.clone(),
        },
    );
    let proxy = match std::fs::metadata(&tok_path) {
        _ if table.is_empty() => proxy,
        Ok(m)
            if m.permissions().mode() & 0o077 == 0
                && !cops_auth::Token::from_file(&tok_path).is_empty() =>
        {
            for (method, pattern) in table.routes() {
                eprintln!("copsd: yerel uç açık: {method} {pattern}");
            }
            proxy.with_route_table(table, cops_auth::Token::from_file(&tok_path))
        }
        _ => {
            eprintln!("copsd: rota tablosu kapalı: web.token yok ya da 0600 değil");
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
    let proxy = match h.routes {
        Some(r) => proxy.with_routes(r),
        None => proxy,
    };
    cops_proxy::serve(listen, proxy).await
}
