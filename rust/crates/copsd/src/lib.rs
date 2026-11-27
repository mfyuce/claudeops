//! copsd: OSS ön sunucu. D0 = saf vekil: `--listen` (varsayılan 127.0.0.1:8765) -> `--upstream` (Python iç port, varsayılan
//! [`DEFAULT_UPSTREAM`] = 127.0.0.1:28765, `cops front` `DEFAULT_INTERNAL` ile aynı).
//! Ön kapı gizlisi: `CLAUDEOPS_FRONT_SECRET` (boş değilse) ya da `--secret-file` (varsayılan [`state_dir`]`/front.secret`,
//! Python `front.secret_path` ile aynı). Dosya her sorguda `stat` edilir, değişince yeniden okunur; yok, gevşek (0600 değil) ya da
//! bozuksa gizli YOK sayılır (kapalı yön), açılışta uyarı yazılır, süreç sürer; bkz. [`cops_proxy::front`].
//! `--dist <py/webui/dist>`: /assets/* ve /favicon.svg diskten sunulur (yoksa Python'a aktarılır).
//! `--mounts-file` (varsayılan [`state_dir`]`/derbent/mounts.json`): uygulama mount'ları (`/<id>/` -> yerel derbent loopback portu,
//! kimlik copsd'de). Dosya yoksa ya da 0600 değilse mount kapalı; 2 sn'de bir değişiklik yoklanır. web.token hazır olana dek mount kapalıdır.
//! Yerel/metrik/mount/rota uçları `web.token` (0600, dolu) ilk hazır olunca açılır (sonradan yazılsa da); değeri her istekte
//! dosyadan okunur (silme/döndürme anında geçerli).
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
pub mod state;

use std::future::Future;
use std::net::SocketAddr;
use std::sync::Arc;

/// Kanca kurucusuna verilen, copsd'nin çözdüğü ayarlar.
pub struct Ctx {
    /// Python iç portu.
    pub upstream: SocketAddr,
    /// Ön kapı gizlisinin AÇILIŞ anındaki değeri; yoksa `None`. Gizli çalışırken değişebilir: [`Ctx::front`] kullanın.
    pub front_secret: Option<String>,
    /// Canlı ön kapı gizlisi (`X-Cops-Front`): her sorguda [`cops_proxy::front::FrontSecret::current`] (vekille aynı nesne).
    pub front: Arc<cops_proxy::front::FrontSecret>,
}

/// `--upstream`/`COPSD_UPSTREAM` verilmezse Python iç portu (`py/claudeops/commands/front_cmd.py` `DEFAULT_INTERNAL`).
pub const DEFAULT_UPSTREAM: &str = "127.0.0.1:28765";

/// Derlenen kaynağın git commit'i (`build.rs`).
pub const GIT_SHA: &str = env!("COPSD_GIT_SHA");

/// Komut satırında `name` bayrağının değeri.
pub fn arg(name: &str) -> Option<String> {
    let a: Vec<String> = std::env::args().collect();
    a.iter()
        .position(|x| x == name)
        .and_then(|i| a.get(i + 1).cloned())
}

/// Durum dizini: `--state-dir`, yoksa [`cops_state::StateDir::resolve`] (`CLAUDEOPS_DIR` boş değilse; cargo test ikilisinde
/// süreç başına GEÇİCİ dizin, H16; yoksa `$HOME/.claude/claudeops`), `HOME` tanımsız/boşsa `os.path.expanduser("~")` kuralı
/// (passwd ev dizini; Python `paths.CLAUDEOPS_DIR` ile aynı). Enterprise `copsd-ent` de bunu kullanır.
pub fn state_dir() -> std::path::PathBuf {
    if let Some(d) = arg("--state-dir") {
        return d.into();
    }
    match cops_state::StateDir::resolve() {
        Ok(d) => d.root().to_path_buf(),
        Err(_) => std::path::PathBuf::from(cops_state::paths::home()).join(".claude/claudeops"),
    }
}

/// `cops-tmux`un yutulan hatası için copsd günlük satırı. Metin tmux stderr'i ya da G/Ç hatasıdır (gönderilen metni
/// içermez, `cops-tmux` sözleşmesi); yine de günlüğe yalnız İLK satırı, denetim karakterleri `?` yapılarak ve
/// [`SWALLOW_TEXT_MAX`] karakterle kırpılarak girer (çok satırlı/uzun bir çıktı pane metni taşıyabilir).
pub fn tmux_swallow_line(kind: cops_tmux::Swallowed, count: u64, err: &str) -> String {
    let first = err.lines().next().unwrap_or("");
    let mut text: String = first
        .chars()
        .take(SWALLOW_TEXT_MAX)
        .map(|c| if c.is_control() { '?' } else { c })
        .collect();
    if first.chars().count() > SWALLOW_TEXT_MAX || err.trim_end().contains('\n') {
        text.push_str(" [kırpıldı]");
    }
    format!(
        "copsd: tmux yutulan hata {} (toplam {count}): {text}",
        kind.code()
    )
}

/// Günlüğe giren yutulan hata metninin üst sınırı (karakter).
pub const SWALLOW_TEXT_MAX: usize = 160;

fn log_tmux_swallow(kind: cops_tmux::Swallowed, err: &str) {
    eprintln!(
        "{}",
        tmux_swallow_line(kind, cops_tmux::swallowed_count(kind), err)
    );
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

/// Gizli dosyasının yolu: `--secret-file`, yoksa [`state_dir`]`/front.secret` (Python `front.secret_path` ile aynı).
pub fn secret_file() -> std::path::PathBuf {
    state_path("--secret-file", "front.secret")
}

/// Açılışta bir kez: gizli ortamdan gelmiyorsa ve dosya VAR ama kullanılamıyorsa yüksek sesle günlüğe yazar. Süreç ÇIKMAZ
/// (çıkış systemd yeniden başlatma döngüsüyle dış portu düşürürdü): gizli YOK sayılır, çalışma anı ve Python ile aynı.
fn warn_unusable_secret(front: &cops_proxy::front::FrontSecret) {
    let Some(path) = front.path() else {
        return;
    };
    if let cops_proxy::front::SecretFile::Unusable(why) = cops_proxy::front::read_secret_file(path)
    {
        eprintln!(
            "copsd: UYARI: ön kapı gizlisi KULLANILMIYOR: {}: {why}. Gizli yok sayılıyor (Python iç ucu güvenmez); \
             düzeltmek için `cops front on --apply`",
            path.display()
        );
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
                    "copsd: SIGHUP: force_proxy okunamadı, TÜM istekler Python'a: {}: {e}",
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
    // `cops-tmux` yutulan hataları copsd günlüğüne (yoksa kendi stderr satırı). İkinci kurulum (aynı süreçte yeniden
    // `run_*`) değişiklik yapmaz.
    cops_tmux::set_swallow_hook(log_tmux_swallow);
    let listen: SocketAddr = arg("--listen")
        .or_else(|| std::env::var("COPSD_LISTEN").ok())
        .unwrap_or_else(|| "127.0.0.1:8765".into())
        .parse()
        .expect("--listen");
    let up: SocketAddr = arg("--upstream")
        .or_else(|| std::env::var("COPSD_UPSTREAM").ok())
        .unwrap_or_else(|| DEFAULT_UPSTREAM.into())
        .parse()
        .expect("--upstream");
    // Tek gizli kaynağı: vekil ve kancalar ([`Ctx::front`]) aynı nesneyi okur. Gizli ortamdan geldiyse sabit, dosyadan ise her
    // sorguda imza denetimiyle (döndürme/silme/sonradan oluşma anında etkili).
    let front = Arc::new(cops_proxy::front::FrontSecret::from_env_or_file(
        secret_file(),
    ));
    warn_unusable_secret(&front);
    let secret = front.current();
    let front_secret = secret.clone().unwrap_or_default();
    eprintln!(
        "copsd {GIT_SHA}: {listen} -> {up} (gizli: {})",
        if secret.is_some() {
            "var"
        } else {
            "YOK: Python X-Forwarded-For'a güvenmez; uzak istemci adresi Cf-Connecting-IP ile iletilir"
        }
    );
    let proxy = cops_proxy::Proxy::new(up)
        .with_front_secret(front.clone())
        .with_version(GIT_SHA);
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
    // Yerel uçlar (Aşama 1): token dosyası (0600, dolu) ve DB hazır olana dek uç KAPALI (istek Python'a gider; vekil ilk
    // hazır oluşta açar, yeniden başlatma gerekmez).
    let tok_path = token_file();
    let db_path = state_path("--db", "claudeops.db");
    let tok_ready = !cops_auth::Token::from_file(&tok_path).is_empty();
    if tok_ready && db_path.exists() {
        eprintln!("copsd: yerel uç açık: GET /api/steward/questions");
    } else {
        eprintln!("copsd: yerel uç kapalı: web.token (0600) ya da DB henüz yok");
    }
    let proxy = proxy.with_local(cops_proxy::LocalCfg {
        token: cops_auth::Token::from_file(&tok_path),
        db: db_path.clone(),
    });
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
    let proxy = match store {
        Some(store) => {
            if tok_ready {
                eprintln!("copsd: metrik uçları açık: /api/metrics/points|series|names");
            } else {
                eprintln!("copsd: metrik uçları kapalı: web.token yok ya da 0600 değil");
            }
            proxy.with_metrics(cops_proxy::MetricsCfg {
                store,
                token: cops_auth::Token::from_file(&tok_path),
                front_secret: cops_auth::Token::new(&front_secret),
            })
        }
        None => proxy,
    };
    // Uygulama mount'ları: kimlik web.token (0600) + `cops_ext` çerezi; token hazır olana dek mount KAPALI (istek Python'a).
    let mounts_file = state_path("--mounts-file", "derbent/mounts.json");
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
    if !tok_ready {
        eprintln!("copsd: mount kapalı: web.token yok ya da 0600 değil");
    }
    mounts.spawn_watch(std::time::Duration::from_secs(2));
    let proxy = proxy.with_mounts(cops_proxy::MountCfg {
        mounts,
        token: cops_auth::Token::from_file(&tok_path),
    });
    // Çoklu rota tablosu: panel kimlikli kayıtlar web.token ister; yoksa tablo AÇILMAZ (istek Python'a gider).
    let mut table = cops_proxy::routes::RouteTable::new();
    routes::register(
        &mut table,
        &routes::RouteCtx::new(state_dir(), db_path.clone(), instances.clone()),
    );
    let proxy = if table.is_empty() {
        proxy
    } else {
        for (method, pattern) in table.routes() {
            let state = if tok_ready {
                "açık"
            } else {
                "kapalı (web.token yok)"
            };
            eprintln!("copsd: yerel uç {state}: {method} {pattern}");
        }
        proxy.with_route_table(table, cops_auth::Token::from_file(&tok_path))
    };
    let h = hooks(Ctx {
        upstream: up,
        front_secret: Some(front_secret).filter(|s| !s.is_empty()),
        front,
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
