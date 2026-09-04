/**
 * i18n strings — 1:1 port of the `const T = { tr: {...}, en: {...} }` object
 * embedded in the original `web.py`'s `PAGE_HTML` (client-side JS blob).
 *
 * React rewrite plan (dynamic-crunching-lemon.md), Sequencing step 4.
 * Dependency-free by design (no i18next) — both languages are known at
 * build time and the `Strings` interface below is the whole point: any
 * language object that's missing a key, has a key with the wrong function
 * arity, or is referenced with a typo'd key at a call site now fails
 * `tsc`, none of which were caught before this port.
 *
 * Porting note (why this isn't a naive copy-paste of web.py's source
 * text): `PAGE_HTML` is a non-raw Python triple-quoted string, so Python's
 * own string-literal parsing already consumed one layer of backslash
 * escaping before this JS ever reached a browser — e.g. the file text
 * `\\n` inside a JS template literal becomes the real 2-character JS
 * escape `\n` only *after* Python de-escapes it once. (This exact
 * class of bug bit this codebase before — see the project's own
 * `web-embedded-js-escaping-trap` note.) Porting the raw file bytes
 * verbatim into this standalone .ts file — which has no Python layer
 * above it — would double the escaping and turn intended newlines into
 * literal backslash-n text. To avoid transcribing that by hand across
 * 130 keys, the values below were extracted by parsing web.py's real
 * `PAGE_HTML` string via Python's `ast` module (i.e. the exact bytes a
 * browser used to receive), then re-serialized here with each plain
 * string run through `JSON.stringify` (correct, single-layer escaping)
 * and each of the 13 function values taken from its own
 * `Function.prototype.toString()` (exact source text, escape sequences
 * preserved as source syntax) — then verified key-for-key against the
 * original (130 keys, exact match in both languages, 13 function-valued
 * keys in both, matching arities). Only two keys actually contained an
 * escape needing this correction: `bulkConfirm` and `diagTestFailStderr`
 * (both `\\n` -> `\n`, tr and en).
 *
 * The 13 function-valued keys' parameter types below are NOT guessed —
 * each was resolved by reading its actual call site(s) in web.py's JS
 * (e.g. `fallbackAlertMsg(d.diag.recent_fallback_count,
 * d.diag.fallback_alert_window_minutes)` -> both numbers per
 * `DiagInfo`; `diagWindowless(windowless.join(', '))` -> the caller
 * already joins the array, so the param is `string`, not `string[]`;
 * `diagRestartDone(d.result)` -> backend `_diag_restart_gt()` returns
 * `kill_session()`'s `KillResult`, a string).
 */

export type Lang = "tr" | "en";

export interface Strings {
  title: string;
  colName: string;
  colStatus: string;
  colKind: string;
  serverUnreachable: string;
  authError: string;
  authErrorShort: string;
  unexpectedResponse: (code: number) => string;
  runningWord: string;
  configWord: string;
  /** Renders `StatusPayload.config_code`/`config_detail` (backend returns a
   * language-neutral code — same "backend returns raw data, this file
   * localizes it" pattern as `fallbackAlertMsg` etc). */
  configMsg: (code: string, detail: string) => string;
  dupWarn: string;
  fallbackAlertMsg: (n: number, mins: number) => string;
  fallbackAlertBtn: string;
  pidWord: string;
  stoppedWord: string;
  cwdHint: string;
  requestFailed: string;
  empty: string;
  cancelBtn: string;
  tabRunning: string;
  tabRegistered: string;
  tabDisabled: string;
  tabRetired: string;
  tabLayout: string;
  tabDesktop: string;
  tabDiag: string;
  tabSettings: string;
  desktopDesc: string;
  desktopStartBtn: string;
  desktopStopBtn: string;
  desktopStarting: string;
  desktopStopping: string;
  desktopConnecting: string;
  desktopWaitingFrame: string;
  selWord: string;
  selectNeedsHo: string;
  hoCol: string;
  hoHint: string;
  hoUnknown: string;
  stopBtn: string;
  disableBtn: string;
  retireBtn: string;
  handoverBtn: string;
  compactBtn: string;
  legendStop: string;
  legendDisable: string;
  legendRetire: string;
  legendHandover: string;
  legendCompact: string;
  bulkConfirm: (label: string, expl: string, names: string[]) => string;
  bulkSkippedUnreg: string;
  bulkDone: (ok: number, fail: number) => string;
  optionsBtn: string;
  startBtn: string;
  terminalBtn: string;
  termPlaceholder: string;
  termSend: string;
  termGone: (err: string) => string;
  termScrolledHint: string;
  termCopyBtn: string;
  termCopied: string;
  termCopyHint: string;
  termOpen: string;
  tabTermView: string;
  tabChatView: string;
  chatModeLast: string;
  chatModeFull: string;
  chatYou: string;
  chatAssistant: string;
  chatEmpty: string;
  chatUnsupported: string;
  chatLoadError: string;
  nothingRunning: string;
  unregBadge: string;
  unregHint: string;
  adoptBtn: string;
  adoptWarn: (name: string) => string;
  adoptNameLabel: string;
  adopting: string;
  adopted: string;
  noneRegistered: string;
  registerTitle: string;
  registerDesc: string;
  registerNameLabel: string;
  registerCwdLabel: string;
  registerSave: string;
  registerSaving: string;
  reactivateBtn: string;
  modeResume: string;
  modeReset: string;
  modeNewchat: string;
  modeChoiceNewchatOnly: string;
  modeChoiceResume: string;
  modeChoiceReset: string;
  modeChoiceNewchat: string;
  runningNote: (name: string) => string;
  pmLabel: string;
  effortLabel: string;
  modelLabel: string;
  cliLabel: string;
  autoNameHint: (name: string, date: string) => string;
  starting: string;
  newChatStarted: string;
  layoutDesc: string;
  layoutMissingPrefix: string;
  layoutMissingSuffix: string;
  layoutPinLabel: string;
  layoutGroupsLabel: string;
  layoutClaudeOnly: string;
  layoutDryRun: string;
  layoutApply: string;
  layoutApplying: string;
  windowsWord: string;
  skippedWord: string;
  diagDesc: string;
  diagWebUptime: string;
  diagGtUptime: string;
  diagUptimeUnknown: string;
  diagGtNotFound: string;
  diagTestBtn: string;
  diagTesting: string;
  diagTestOk: string;
  diagTestFailWindow: string;
  diagTestFailStderr: (e: string) => string;
  diagRestartBtn: string;
  diagRestartConfirm: (n: number) => string;
  diagRestarting: string;
  diagRestartDone: (r: string) => string;
  diagRefreshHint: string;
  diagWindowless: (names: string) => string;
  windowlessBadge: string;
  windowlessHint: string;
  openWindowBtn: string;
  openingWindow: string;
  diagAskCliLabel: string;
  diagAskQuestionLabel: string;
  diagAskQuestionPlaceholder: string;
  diagAskBtn: string;
  diagAsking: string;
  diagAskStarted: (name: string) => string;
  diagLogTitle: string;
  diagLogLoading: string;
  diagRunAfterFail: string;
  handoverMsgTitle: string;
  handoverMsgHint: string;
  protectedBadge: string;
  protectedHint: string;
  settingsDesc: string;
  settingsAuto: string;
  settingsAutoModel: (model: string) => string;
  themeLabel: string;
  themeSystem: string;
  themeLight: string;
  themeDark: string;
  handoverEffortLabel: string;
  handoverEffortHint: string;
  defaultModelLabel: string;
  pagePrev: string;
  pageNext: string;
  pageOf: (page: number, total: number) => string;
  groupRunningBadge: string;
  searchPlaceholder: string;
  searchClear: string;
  noSearchMatches: string;
}

export const STRINGS: Record<Lang, Strings> = {
  tr: {
    title: "claudeops — filo kontrolü",
    colName: "isim",
    colStatus: "durum",
    colKind: "tür",
    serverUnreachable: "sunucuya ulaşılamadı: ",
    authError: "401 — token eksik/yanlış (URL'ye doğru ?token=... ekleyin)",
    authErrorShort: "401 — token eksik/yanlış",
    unexpectedResponse: (code) => `beklenmeyen yanıt (http ${code}) — bu tünel/URL artık geçerli olmayabilir, güncel linki kontrol edin`,
    runningWord: "çalışıyor",
    configWord: "config",
    configMsg: (code, detail) => code === "valid" ? "~/.claude.json geçerli" : code === "not_found" ? "~/.claude.json bulunamadı" : code === "corrupt" ? `~/.claude.json BOZUK (${detail}) — ~/.claude/backups/'tan geri yükle` : `~/.claude.json okunamadı: ${detail}`,
    dupWarn: "⚠ DUP: ",
    fallbackAlertMsg: (n, mins) => `⚠ son ${mins} dakikada ${n} kez pencere açma tüm denemelere (retry dahil) rağmen başarısız oldu (CLI'lar yine de çalışıyor, sadece penceresiz) — gnome-terminal-server gerçekten sorunlu olabilir.`,
    fallbackAlertBtn: "Tanı sekmesine git",
    pidWord: "pid ",
    stoppedWord: "durdu",
    cwdHint: "tıkla: tam yolu göster/gizle",
    requestFailed: "istek başarısız: ",
    empty: "Boş.",
    cancelBtn: "vazgeç",
    tabRunning: "Çalışanlar",
    tabRegistered: "Kayıtlı",
    tabDisabled: "Devre dışı",
    tabRetired: "Emekli",
    tabLayout: "Layout",
    tabDesktop: "Uzak Masaüstü",
    tabDiag: "Tanı",
    tabSettings: "Ayarlar",
    desktopDesc: "Makinenin ekran görüntüsünü canlı izle (2 fps, salt-izleme — mouse/klavye kontrolü yok). Kapatmayı unutma, açıkken sürekli ekran yakalıyor.",
    desktopStartBtn: "Başlat",
    desktopStopBtn: "Durdur",
    desktopStarting: "başlatılıyor… (ilk seferde derleme birkaç saniye sürebilir)",
    desktopStopping: "durduruluyor…",
    desktopConnecting: "bağlanıyor…",
    desktopWaitingFrame: "ilk görüntü bekleniyor…",
    selWord: "seçili",
    selectNeedsHo: "needs-ho seç",
    hoCol: "ho?",
    hoHint: "handover gerekli mi? (repo kirli / untracked / baseline'dan beri commit / RFH yok — sinyallerden biri)",
    hoUnknown: "?",
    stopBtn: "durdur",
    disableBtn: "devre dışı bırak",
    retireBtn: "emekli et",
    handoverBtn: "handover",
    compactBtn: "compact",
    legendStop: "sadece process/pencereyi kapatır — kayıt AKTİF kalır, \"Kayıtlı\" sekmesinden devam ettirilir",
    legendDisable: "durdurur + otomasyon (guard) bir daha AÇMAZ — \"Devre dışı\" sekmesine taşınır, oradan geri alınır",
    legendRetire: "durdurur + arşive kaldırır — \"Emekli\" sekmesine taşınır, \"tekrar işe al\" ile döner",
    legendHandover: "wrap-up mesajı gönderip AYNI geçmişle yeniden açar (kapat+devam) — commit/push + not düşme için",
    legendCompact: "konuşmayı sıkıştırıp (context özetlenir) AYNI geçmişle yeniden açar — sadece claude CLI, birkaç dakika sürebilir",
    bulkConfirm: (label, expl, names) => `${label} — ${expl}\n\nseçili (${names.length}): ${names.join(', ')}\n\nDevam edilsin mi?`,
    bulkSkippedUnreg: "kayıtsız olduğu için atlanacak: ",
    bulkDone: (ok, fail) => `bitti — ${ok} tamam` + (fail ? `, ${fail} hata` : ''),
    optionsBtn: "seçenekler ▾",
    startBtn: "başlat ▾",
    terminalBtn: "terminal",
    termPlaceholder: "komut yaz, Enter/Gönder ile yolla…",
    termSend: "gönder",
    termGone: (err) => `✗ ${err}`,
    termScrolledHint: "⏸ yukarı kaydırdınız — canlı akış duraklatıldı, dibe dönünce devam eder",
    termCopyBtn: "kopyala",
    termCopied: "✓ kopyalandı",
    termCopyHint: "görünen çıktıyı panoya kopyala (mobilde dokunarak seçim güvenilir değil)",
    termOpen: "aç",
    tabTermView: "terminal",
    tabChatView: "sohbet",
    chatModeLast: "son mesaj",
    chatModeFull: "tüm session",
    chatYou: "Sen",
    chatAssistant: "Asistan",
    chatEmpty: "(boş)",
    chatUnsupported: "bu CLI için sohbet görünümü henüz yok — terminal sekmesini kullanın",
    chatLoadError: "yüklenemedi: ",
    nothingRunning: "Hiçbir şey çalışmıyor — \"Kayıtlı\" sekmesinden başlatın.",
    unregBadge: "kayıtsız",
    unregHint: "roster.tsv'de kayıtlı değil (proc-scan'den bulundu) — claudeops'un açmadığı bir pencere; \"devral\"a basarsanız remote-control eklenip roster'a kalıcı kaydedilir",
    adoptBtn: "devral (remote ekle)",
    adoptWarn: (name) => `⚠ ${name} claudeops'un açmadığı bir pencere (elle/başka yerden açılmış). "devral" bu pencereyi KAPATIR ve seçtiğiniz isimle AYRI, YENİ bir pencerede --remote-control ile açar (aynı geçmişle, --resume) — şu an baktığınız pencerenin kendisi değil, yeni bir pencere.`,
    adoptNameLabel: "yeni isim (remote-control adı)",
    adopting: "devralınıyor… (~10-20s)",
    adopted: "devralındı, yeni isim: ",
    noneRegistered: "Durdurulmuş kayıtlı proje yok — hepsi çalışıyor ya da liste boş.",
    registerTitle: "+ Yeni proje kaydet",
    registerDesc: "(klasörü roster'a ekler, başlatmaz — sonra yukarıdaki listeden başlatırsınız)",
    registerNameLabel: "isim (küçük harf, rakam, _)",
    registerCwdLabel: "klasör (tam yol)",
    registerSave: "kaydet",
    registerSaving: "kaydediliyor…",
    reactivateBtn: "tekrar işe al + başlat",
    modeResume: "devam ettir",
    modeReset: "sıfırla ve başlat",
    modeNewchat: "yeni chat aç",
    modeChoiceNewchatOnly: "Ayrı yeni chat aç (mevcuduna dokunmaz)",
    modeChoiceResume: "Devam ettir (kaldığı yerden)",
    modeChoiceReset: "Bu ismi SIFIRLA (--new, geçmiş bir daha görünmez)",
    modeChoiceNewchat: "Ayrı yeni chat aç (yeni isimle, mevcuduna dokunmaz)",
    runningNote: (name) => `⚠ ${name} şu an ÇALIŞIYOR — devam ettirmek/sıfırlamak için önce "durdur"a basın. Buradaki tek seçenek AYRI, ek bir chat açar, mevcut ${name}'a dokunmaz.`,
    pmLabel: "permission-mode",
    effortLabel: "effort",
    modelLabel: "model",
    cliLabel: "CLI",
    autoNameHint: (name, date) => `isim otomatik: ${name}${date} (çakışırsa _1, _2…)`,
    starting: "başlıyor…",
    newChatStarted: "yeni chat başlatıldı: ",
    layoutDesc: "X11 masaüstü — Wayland'da/kilitli ekranda çalışmaz",
    layoutMissingPrefix: "⚠ eksik: ",
    layoutMissingSuffix: " — kurmak için: sudo apt install -y ",
    layoutPinLabel: "pin (ws0'a sabit, virgülle)",
    layoutGroupsLabel: "group'lar ( | ile ayrılmış birden fazla grup, her grup virgüllü)",
    layoutClaudeOnly: "sadece claude pencereleri",
    layoutDryRun: "sadece planı göster (uygulama)",
    layoutApply: "layout uygula",
    layoutApplying: "uygulanıyor…",
    windowsWord: "pencere",
    skippedWord: "atlandı",
    diagDesc: "Fleet'in tüm \"start\"ları sessizce başarısız olabiliyor — iki bağımsız, birbirinden ayrı sebepten (web sunucu ya da gnome-terminal-server'ın kendi uzun çalışma süresi). Aşağıda ikisinin durumu + tek-tıkla test/fix.",
    diagWebUptime: "web sunucu (bu panel)",
    diagGtUptime: "gnome-terminal-server",
    diagUptimeUnknown: "bilinmiyor",
    diagGtNotFound: "çalışmıyor (henüz hiç pencere açılmamış olabilir — sorun değil)",
    diagTestBtn: "spawn sağlık testi",
    diagTesting: "test ediliyor… (~2s, kısa bir pencere açılıp kendi kendine kapanacak)",
    diagTestOk: "✓ gnome-terminal sağlıklı — test penceresi başarıyla açıldı ve doğrulandı",
    diagTestFailWindow: "✗ pencere açılmadı/doğrulanamadı",
    diagTestFailStderr: (e) => `✗ gnome-terminal hata verdi:\n${e}`,
    diagRestartBtn: "gnome-terminal-server'ı yeniden başlat",
    diagRestartConfirm: (n) => `Açık TÜM gnome-terminal pencereleri kapanacak (fleet'in ${n} çalışan penceresi dahil, varsa filoyla ilgisiz başka terminal pencereleri de) — tmux session'lar/claude process'leri ETKİLENMEZ, sadece görünür pencereler kaybolur. Bir sonraki pencere açma isteğinde otomatik yeniden doğar. Devam edilsin mi?`,
    diagRestarting: "yeniden başlatılıyor…",
    diagRestartDone: (r) => `✓ kapatıldı (${r}) — bir sonraki spawn'da otomatik yeniden doğacak`,
    diagRefreshHint: "çalışma süreleri her 4s otomatik güncellenir",
    diagWindowless: (names) => `⚠ penceresiz çalışıyor (gnome-terminal fallback, tmux-only): ${names} — panelde görünmezler, sadece "terminal" butonuyla erişilir`,
    windowlessBadge: "penceresiz",
    windowlessHint: "gnome-terminal penceresi yok (tmux-only fallback) — CLI çalışıyor, sadece görünür pencere yok. \"pencere aç\" ile CLI yeniden başlamadan bir pencere bağlayabilirsin.",
    openWindowBtn: "pencere aç",
    openingWindow: "pencere açılıyor…",
    diagAskCliLabel: "CLI",
    diagAskQuestionLabel: "ek soru (opsiyonel)",
    diagAskQuestionPlaceholder: "boş bırakılırsa genel teşhis istenir",
    diagAskBtn: "bu CLI ile sor",
    diagAsking: "açılıyor… (~10-20s)",
    diagAskStarted: (name) => `✓ açıldı: ${name} — terminal'de canlı yanıt görünecek`,
    diagLogTitle: "son diag-log kayıtları",
    diagLogLoading: "yükleniyor…",
    diagRunAfterFail: "Tanı sekmesine geçip spawn sağlık testi çalıştırılsın mı?",
    handoverMsgTitle: "handover metni",
    handoverMsgHint: "handover butonunun gönderdiği wrap-up mesajı, şu an seçili dilde — ayrı bir CLI açmadan kopyalayıp elle yapıştırabilirsiniz",
    protectedBadge: "dikkat",
    protectedHint: "guard'ı ayakta tutuyor — toplu seçimde/işlemde dikkatli olun",
    settingsDesc: "Bu ayarlar sunucu tarafında saklanır (~/.claude/claudeops/settings.json) — telefon dahil hangi cihaz/tarayıcıdan girerseniz girin aynı görünür. Her seçim anında kaydedilir.",
    settingsAuto: "(otomatik)",
    settingsAutoModel: (model) => `(otomatik: ${model})`,
    themeLabel: "tema",
    themeSystem: "sistem",
    themeLight: "açık",
    themeDark: "koyu",
    handoverEffortLabel: "handover varsayılan effort",
    handoverEffortHint: "handover (Faz 1/Faz 2/panelin tek-session handover butonu) ile yeniden açılan session'ların effort'u — respawn edilen session'ın BİR SONRAKİ handover'a kadarki ömrü boyunca kalıcı varsayılan olur",
    defaultModelLabel: "yeni/resume için varsayılan model (CLI başına)",
    pagePrev: "önceki",
    pageNext: "sonraki",
    pageOf: (page, total) => `sayfa ${page}/${total}`,
    groupRunningBadge: "bu grupta çalışan var",
    searchPlaceholder: "isim veya cwd ara…",
    searchClear: "aramayı temizle",
    noSearchMatches: "Aramayla eşleşen yok.",
  },
  en: {
    title: "claudeops — fleet control",
    colName: "name",
    colStatus: "status",
    colKind: "kind",
    serverUnreachable: "server unreachable: ",
    authError: "401 — token missing/invalid (add ?token=... to the URL)",
    authErrorShort: "401 — token missing/invalid",
    unexpectedResponse: (code) => `unexpected response (http ${code}) — this tunnel/URL may no longer be valid, check the current link`,
    runningWord: "running",
    configWord: "config",
    configMsg: (code, detail) => code === "valid" ? "~/.claude.json is valid" : code === "not_found" ? "~/.claude.json not found" : code === "corrupt" ? `~/.claude.json CORRUPT (${detail}) — restore from ~/.claude/backups/` : `~/.claude.json unreadable: ${detail}`,
    dupWarn: "⚠ DUP: ",
    fallbackAlertMsg: (n, mins) => `⚠ in the last ${mins} minutes, opening a window failed ${n} times despite all retries (the CLIs are still running, just windowless) — gnome-terminal-server may genuinely be having trouble.`,
    fallbackAlertBtn: "go to Diagnostics tab",
    pidWord: "pid ",
    stoppedWord: "stopped",
    cwdHint: "click: show/hide full path",
    requestFailed: "request failed: ",
    empty: "Empty.",
    cancelBtn: "cancel",
    tabRunning: "Running",
    tabRegistered: "Registered",
    tabDisabled: "Disabled",
    tabRetired: "Retired",
    tabLayout: "Layout",
    tabDesktop: "Remote Desktop",
    tabDiag: "Diagnostics",
    tabSettings: "Settings",
    desktopDesc: "Watch the machine's screen live (2 fps, view-only — no mouse/keyboard control). Remember to stop it — it captures the screen continuously while running.",
    desktopStartBtn: "Start",
    desktopStopBtn: "Stop",
    desktopStarting: "starting… (first run may take a few seconds to compile)",
    desktopStopping: "stopping…",
    desktopConnecting: "connecting…",
    desktopWaitingFrame: "waiting for first frame…",
    selWord: "selected",
    selectNeedsHo: "select needs-ho",
    hoCol: "ho?",
    hoHint: "needs handover? (dirty repo / untracked / commits since baseline / no RFH — any one signal)",
    hoUnknown: "?",
    stopBtn: "stop",
    disableBtn: "disable",
    retireBtn: "retire",
    handoverBtn: "handover",
    compactBtn: "compact",
    legendStop: "kills only the process/window — stays REGISTERED, resume it from the \"Registered\" tab",
    legendDisable: "stop + automation (guard) will NOT reopen it — moves to the \"Disabled\" tab, reversible there",
    legendRetire: "stop + archive — moves to the \"Retired\" tab, comes back via \"reactivate\"",
    legendHandover: "sends a wrap-up prompt and reopens with the SAME history (close+continue) — for commit/push + notes",
    legendCompact: "compacts the conversation (summarizes context) and reopens with the SAME history — claude CLI only, can take a few minutes",
    bulkConfirm: (label, expl, names) => `${label} — ${expl}\n\nselected (${names.length}): ${names.join(', ')}\n\nProceed?`,
    bulkSkippedUnreg: "skipped (unregistered): ",
    bulkDone: (ok, fail) => `done — ${ok} ok` + (fail ? `, ${fail} failed` : ''),
    optionsBtn: "options ▾",
    startBtn: "start ▾",
    terminalBtn: "terminal",
    termPlaceholder: "type a command, Enter/Send to submit…",
    termSend: "send",
    termGone: (err) => `✗ ${err}`,
    termScrolledHint: "⏸ scrolled up — live updates paused, resumes when you scroll back to bottom",
    termCopyBtn: "copy",
    termCopied: "✓ copied",
    termCopyHint: "copy visible output to clipboard (touch-selection is unreliable on mobile)",
    termOpen: "open",
    tabTermView: "terminal",
    tabChatView: "chat",
    chatModeLast: "last message",
    chatModeFull: "full session",
    chatYou: "You",
    chatAssistant: "Assistant",
    chatEmpty: "(empty)",
    chatUnsupported: "chat view isn't available for this CLI yet — use the terminal tab",
    chatLoadError: "failed to load: ",
    nothingRunning: "Nothing running — start from the \"Registered\" tab.",
    unregBadge: "unregistered",
    unregHint: "not in roster.tsv (found via proc-scan) — a window claudeops didn't open; click \"adopt\" to attach remote-control and register it permanently",
    adoptBtn: "adopt (attach remote)",
    adoptWarn: (name) => `⚠ ${name} is a window claudeops didn't open (started by hand/elsewhere). "adopt" will CLOSE this window and open a SEPARATE, NEW window under the name you choose, with --remote-control (same history, --resume) — not this exact window, a new one.`,
    adoptNameLabel: "new name (remote-control name)",
    adopting: "adopting… (~10-20s)",
    adopted: "adopted, new name: ",
    noneRegistered: "No stopped registered projects — everything is running, or the list is empty.",
    registerTitle: "+ Register new project",
    registerDesc: "(adds the folder to the roster, does not start it — start it from the list above)",
    registerNameLabel: "name (lowercase, digits, _)",
    registerCwdLabel: "folder (full path)",
    registerSave: "save",
    registerSaving: "saving…",
    reactivateBtn: "reactivate + start",
    modeResume: "resume",
    modeReset: "reset and start",
    modeNewchat: "start new chat",
    modeChoiceNewchatOnly: "Start a separate new chat (does not touch the existing one)",
    modeChoiceResume: "Resume (from where it left off)",
    modeChoiceReset: "RESET this name (--new, previous history no longer shown)",
    modeChoiceNewchat: "Start a separate new chat (new name, does not touch the existing one)",
    runningNote: (name) => `⚠ ${name} is currently RUNNING — click "stop" first to resume/reset. The only option here starts a SEPARATE extra chat, it does not touch the existing ${name}.`,
    pmLabel: "permission-mode",
    effortLabel: "effort",
    modelLabel: "model",
    cliLabel: "CLI",
    autoNameHint: (name, date) => `name auto-generated: ${name}${date} (adds _1, _2… on conflict)`,
    starting: "starting…",
    newChatStarted: "new chat started: ",
    layoutDesc: "X11 desktop — does not work on Wayland/locked screen",
    layoutMissingPrefix: "⚠ missing: ",
    layoutMissingSuffix: " — install with: sudo apt install -y ",
    layoutPinLabel: "pin (fixed to ws0, comma-separated)",
    layoutGroupsLabel: "groups ( | -separated, each group comma-separated)",
    layoutClaudeOnly: "claude windows only",
    layoutDryRun: "show plan only (no changes)",
    layoutApply: "apply layout",
    layoutApplying: "applying…",
    windowsWord: "windows",
    skippedWord: "skipped",
    diagDesc: "Any/all of the fleet's \"start\"s can silently fail — from two independent causes (either the web server's or gnome-terminal-server's own long uptime). Status of both below, plus a one-click test/fix.",
    diagWebUptime: "web server (this panel)",
    diagGtUptime: "gnome-terminal-server",
    diagUptimeUnknown: "unknown",
    diagGtNotFound: "not running (may just be that no window has opened yet — not a problem)",
    diagTestBtn: "spawn health test",
    diagTesting: "testing… (~2s, a brief window will open and close itself)",
    diagTestOk: "✓ gnome-terminal is healthy — the test window opened and was verified",
    diagTestFailWindow: "✗ window did not open / could not be verified",
    diagTestFailStderr: (e) => `✗ gnome-terminal reported an error:\n${e}`,
    diagRestartBtn: "restart gnome-terminal-server",
    diagRestartConfirm: (n) => `ALL open gnome-terminal windows will close (including the fleet's ${n} running window(s), plus any unrelated terminal windows you may have open) — tmux sessions/claude processes are NOT affected, only the visible windows disappear. It respawns automatically on the next window-open request. Proceed?`,
    diagRestarting: "restarting…",
    diagRestartDone: (r) => `✓ stopped (${r}) — will respawn automatically on the next spawn`,
    diagRefreshHint: "uptimes auto-refresh every 4s",
    diagWindowless: (names) => `⚠ running windowless (gnome-terminal fallback, tmux-only): ${names} — won't show a window, only reachable via the "terminal" button`,
    windowlessBadge: "windowless",
    windowlessHint: "no gnome-terminal window (tmux-only fallback) — the CLI is running, it just has no visible window. \"open window\" attaches one without restarting the CLI.",
    openWindowBtn: "open window",
    openingWindow: "opening window…",
    diagAskCliLabel: "CLI",
    diagAskQuestionLabel: "extra question (optional)",
    diagAskQuestionPlaceholder: "leave empty for a general diagnosis",
    diagAskBtn: "ask with this CLI",
    diagAsking: "opening… (~10-20s)",
    diagAskStarted: (name) => `✓ opened: ${name} — the live answer will appear in the terminal`,
    diagLogTitle: "recent diag-log entries",
    diagLogLoading: "loading…",
    diagRunAfterFail: "Switch to the Diagnostics tab and run the spawn health test?",
    handoverMsgTitle: "handover text",
    handoverMsgHint: "the wrap-up message the handover button sends, in the currently selected language — copy it and paste it by hand without opening a separate CLI",
    protectedBadge: "caution",
    protectedHint: "keeps the guard alive — be careful with bulk selection/actions on this row",
    settingsDesc: "These settings are stored server-side (~/.claude/claudeops/settings.json) — the same on every device/browser you sign in from, phone included. Each choice saves instantly.",
    settingsAuto: "(auto)",
    settingsAutoModel: (model) => `(auto: ${model})`,
    themeLabel: "theme",
    themeSystem: "system",
    themeLight: "light",
    themeDark: "dark",
    handoverEffortLabel: "handover default effort",
    handoverEffortHint: "the effort level sessions reopened by handover (Phase 1/Phase 2/the panel's single-session handover button) get — becomes the respawned session's persistent default for its whole life until the NEXT handover",
    defaultModelLabel: "default model for new/resume (per CLI)",
    pagePrev: "prev",
    pageNext: "next",
    pageOf: (page, total) => `page ${page}/${total}`,
    groupRunningBadge: "something in this group is running",
    searchPlaceholder: "search name or cwd…",
    searchClear: "clear search",
    noSearchMatches: "Nothing matches the search.",
  },
};
