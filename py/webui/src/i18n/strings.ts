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

/** The `SessionInfo.phase` fields the phase strings read (structural, so this file stays dependency-free). */
export interface PhaseArg {
  name: string;
  elapsed?: number | null;
  idle?: number | null;
  attempt?: number;
  max_attempts?: number;
  wait_secs?: number;
  detail?: string;
  streamed_bytes?: number;
  warn?: number;
}

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
  busyHint: string;
  idleHint: string;
  stoppedWord: string;
  cwdHint: string;
  requestFailed: string;
  empty: string;
  cancelBtn: string;
  tabRunning: string;
  tabRegistered: string;
  tabUcli: string;
  tabDisabled: string;
  tabRetired: string;
  tabHistory: string;
  tabDesktop: string;
  tabSnapshots: string;
  tabDiag: string;
  tabSettings: string;
  desktopDesc: string;
  desktopStartBtn: string;
  desktopStopBtn: string;
  desktopStarting: string;
  desktopStopping: string;
  desktopConnecting: string;
  desktopWaitingFrame: string;
  desktopControlOnBtn: string;
  desktopControlOffBtn: string;
  desktopControlHint: string;
  desktopCursorToggle: string;
  selWord: string;
  selectNeedsHo: string;
  selectAttention: string;
  selectWindowless: string;
  mirrorAllBtn: string;
  mirrorAllHint: string;
  mirrorAllNone: string;
  mirrorAllConfirm: (names: string[]) => string;
  windowlessSelectHint: string;
  windowlessUnknown: string;
  windowlessNone: string;
  attentionHint: string;
  hoCol: string;
  hoHint: string;
  hoUnknown: string;
  stopBtn: string;
  disableBtn: string;
  retireBtn: string;
  resetBtn: string;
  bulkStartBtn: string;
  handoverBtn: string;
  compactBtn: string;
  legendStop: string;
  legendDisable: string;
  legendRetire: string;
  legendReset: string;
  legendRestart: string;
  legendNewchatBulk: string;
  legendBulkStart: string;
  legendHandover: string;
  legendCompact: string;
  bulkConfirm: (label: string, expl: string, names: string[]) => string;
  bulkSkippedUnreg: string;
  bulkDone: (ok: number, fail: number) => string;
  optionsBtn: string;
  startBtn: string;
  terminalBtn: string;
  remoteTerminalHint: string;
  termPlaceholder: string;
  termMaskedPlaceholder: string;
  termMaskedHint: string;
  termSend: string;
  termLiveLabel: string;
  termLiveHint: string;
  termLiveOn: string;
  termCtrlLabel: string;
  termCtrlHint: string;
  termCtrlOn: string;
  termGone: (err: string) => string;
  termScrolledHint: string;
  termHistoryBtn: string;
  termHistoryBtnHint: string;
  termHistoryLoading: string;
  termLiveBtn: string;
  termLiveBtnHint: string;
  termHistorySize: (size: number, limit: number) => string;
  termHistorySizeHint: string;
  termCopyBtn: string;
  termCopied: string;
  termCopyHint: string;
  termModeLabel: string;
  termModeHint: string;
  termModePick: string;
  termModeApplying: string;
  termModelLabel: string;
  termModelHint: string;
  termModelPick: string;
  termEffortLabel: string;
  termEffortHint: string;
  termOpen: string;
  tabTermView: string;
  tabChatView: string;
  chatModeLast: string;
  chatModeFull: string;
  chatYou: string;
  chatAssistant: string;
  chatEmpty: string;
  chatCompacted: string;
  chatSummary: string;
  chatUnsupported: string;
  chatLoadError: string;
  tabFilesView: string;
  tabInfoView: string;
  viewBtn: string;
  readOnlySessionHint: string;
  filesEmpty: string;
  filesLoadError: string;
  filesUp: string;
  filesDownload: string;
  filesView: string;
  filesRootLabel: string;
  filesOpenVscode: string;
  filesOpenVscodeHint: string;
  filesUpload: string;
  filesUploadHint: string;
  filesUploadError: string;
  filesUploadConfirmOverwrite: string;
  filesNewFolder: string;
  filesNewFolderPrompt: string;
  filesDelete: string;
  filesDeleteConfirm: string;
  filesDeleteConfirmFolder: string;
  filesRename: string;
  filesRenamePrompt: string;
  filesEdit: string;
  filesSave: string;
  filesSaveError: string;
  filesActionError: string;
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
  registerSuccess: (name: string) => string;
  registerSaving: string;
  editBtn: string;
  editTitle: string;
  editSave: string;
  editCancel: string;
  reactivateBtn: string;
  historyDesc: string;
  historyCount: (count: number) => string;
  historyResumeBtn: string;
  historyForgetBtn: string;
  historyForgetConfirm: (name: string) => string;
  historyNoBlueprint: string;
  historyHostError: (host: string, msg: string) => string;
  instanceBadgeHint: (blueprint: string) => string;
  modeResume: string;
  modeReset: string;
  modeNewchat: string;
  modeRestart: string;
  modeChoiceNewchatOnly: string;
  modeChoiceResume: string;
  modeChoiceReset: string;
  modeChoiceNewchat: string;
  modeChoiceRestart: string;
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
  usageBadge: (tokens: string, requests: number, floor: boolean, quota?: string) => string;
  usageHint: (u: {
    requests: number;
    reported: number;
    prompt_tokens: number;
    cached_tokens: number;
    completion_tokens: number;
    reasoning_tokens: number;
    unmetered: number;
    quota_tokens?: number;
    warn?: number;
  }) => string;
  cacheDur: (minutes: number) => string;
  cacheBadge: (state: "warm" | "expiring" | "cold", dur: string) => string;
  cacheHint: (state: "warm" | "expiring" | "cold", age: string, left: string) => string;
  phaseBadge: (p: PhaseArg) => string;
  phaseHint: (p: PhaseArg) => string;
  pmAllowCreateHint: string;
  openWindowBtn: string;
  openingWindow: string;
  mirrorBtn: string;
  mirrorBtnHint: (host: string) => string;
  mirrorStateOpen: string;
  mirrorStateClosed: string;
  openingMirror: string;
  mirrorOpened: (label: string) => string;
  mirrorAlreadyOpen: (label: string, focused: boolean) => string;
  diagAskCliLabel: string;
  diagAskQuestionLabel: string;
  diagAskQuestionPlaceholder: string;
  diagAskBtn: string;
  diagAsking: string;
  diagAskStarted: (name: string) => string;
  /** `IoAskPanel`'in "backend ham veri döner, React yerelleştirir" katmanı —
   * `io_providers/base.py::FormField.key`'e göre gerçek TR/EN label/
   * placeholder. Tanımadığı bir key (ileride başka bir provider'dan)
   * backend'in kendi (İngilizce/teknik) `label`/`placeholder`'ına düşer. */
  ioFieldMeta: Record<string, { label: string; placeholder?: string }>;
  diagUcliHint: string;
  diagUcliCwdLabel: string;
  diagUcliCwdPlaceholder: string;
  diagUcliNewSession: string;
  diagUcliNewSessionNameLabel: string;
  diagUcliPromptLabel: string;
  diagUcliPromptPlaceholder: string;
  diagUcliModelLabel: string;
  diagUcliEndpointLabel: string;
  diagUcliEndpointPlaceholder: string;
  diagUcliApiKeyLabel: string;
  diagUcliSessionLabel: string;
  diagUcliSessionPlaceholder: string;
  diagUcliBtn: string;
  diagUcliAsking: string;
  diagUcliResult: (answer: string, rounds: number, calls: number) => string;
  diagLogTitle: string;
  diagLogLoading: string;
  diagRunAfterFail: string;
  handoverMsgTitle: string;
  handoverMsgHint: string;
  protectedBadge: string;
  protectedHint: string;
  hostBadgeHint: (host: string) => string;
  modelLiveDiffersHint: (registered: string) => string;
  hostsUnreachableMsg: (names: string[]) => string;
  hostsTitle: string;
  hostsDesc: string;
  hostNameLabel: string;
  hostBaseUrlLabel: string;
  hostTokenLabel: string;
  hostExtraUrlsLabel: string;
  hostExtraUrlsHint: string;
  hostAddBtn: string;
  hostAdding: string;
  hostSaveBtn: string;
  hostSaving: string;
  hostEditBtn: string;
  hostCancelEdit: string;
  hostTokenKeepHint: string;
  hostRemoveBtn: string;
  hostRemoveConfirm: (name: string) => string;
  hostTestBtn: string;
  hostTesting: string;
  hostNone: string;
  cliInstallLabel: string;
  cliInstallDesc: string;
  cliInstallBtn: string;
  cliInstalling: string;
  cliUpdateBtn: string;
  cliManagedByUs: string;
  cliFoundElsewhere: string;
  cliManualOnly: string;
  cliInstallHostLabel: string;
  cliInstallHostUnreachable: string;
  cliInstallHostOutdated: string;
  hostConnected: string;
  hostUnreachable: string;
  hostLocalLabel: string;
  tunnelInfoLabel: string;
  tunnelNoneMsg: string;
  settingsDesc: string;
  settingsSingleUserWarning: string;
  settingsAuto: string;
  settingsAutoModel: (model: string) => string;
  themeLabel: string;
  themeSystem: string;
  themeLight: string;
  themeDark: string;
  handoverEffortLabel: string;
  handoverEffortHint: string;
  historyWarnLabel: string;
  historyWarnHint: string;
  layoutGridLabel: string;
  layoutGridHint: string;
  fleetSortLabel: string;
  fleetSortHint: string;
  fleetSortByName: string;
  fleetSortByCwd: string;
  snapshotLabel: string;
  snapshotDesc: string;
  snapshotNone: string;
  snapshotInfo: (count: number, when: string, kind: "manual" | "closing") => string;
  snapshotSaveBtn: string;
  snapshotSaving: string;
  snapshotResumeBtn: string;
  snapshotResuming: string;
  snapshotHiddenLabel: string;
  snapshotResultSummary: (started: number, alreadyRunning: number, failed: number) => string;
  snapshotMirrorsSuffix: (mirrors: number) => string;
  snapshotMirrorResult: (opened: number, alreadyOpen: number, failed: number, skipped: number) => string;
  snapshotKindManual: string;
  snapshotKindClosing: string;
  snapshotHistoryLabel: string;
  snapshotHistoryEmpty: string;
  snapshotHistoryRow: (count: number, when: string) => string;
  snapshotHistoryResumeBtn: string;
  defaultModelLabel: string;
  providerBinLabel: string;
  providerBinDesc: string;
  providerBinPlaceholder: string;
  byokLabel: string;
  byokDesc: string;
  byokSetPlaceholder: string;
  byokEmptyPlaceholder: string;
  byokClearBtn: string;
  ucliLimitsLabel: string;
  ucliLimitsDesc: string;
  ucliLimitsMaxStepsLabel: string;
  ucliLimitsMaxContextKibLabel: string;
  ucliLimitsMaxToolCallsLabel: string;
  ucliLimitsMaxOutputTokensLabel: string;
  ucliLimitsPlaceholderAuto: string;
  ucliLimitsReasoningLabel: string;
  ucliLimitsReasoningHint: string;
  ucliLimitsReasoningAuto: string;
  ucliLimitsReasoningOff: string;
  ucliLimitsStreamLabel: string;
  ucliLimitsStreamHint: string;
  ucliLimitsStreamOff: string;
  ucliLimitsStreamOn: string;
  ucliUsageWarnLabel: string;
  ucliUsageWarnDesc: string;
  ucliUsageWarnAmberLabel: string;
  ucliUsageWarnRedLabel: string;
  ucliUsageWarnPlaceholder: (def: string) => string;
  tunnelWatchLabel: string;
  tunnelWatchHint: string;
  tunnelWatchOn: string;
  tunnelWatchOff: string;
  defaultEffortLabel: string;
  routingGuidanceLabel: string;
  routingGuidanceDesc: string;
  routingGuidancePlaceholder: string;
  ucliWebLabel: string;
  ucliWebDesc: string;
  ucliWebSearchUrlLabel: string;
  ucliWebSearchUrlPlaceholder: string;
  ucliWebSearchUrlHint: string;
  ucliWebDockerLabel: string;
  ucliWebDockerHint: string;
  ucliWebDockerAuto: string;
  ucliWebDockerOff: string;
  ucliWebFetchLabel: string;
  ucliWebFetchPlaceholder: string;
  ucliWebFetchHint: string;
  ucliWebStateUrl: (url: string) => string;
  ucliWebStateUrlInvalid: string;
  ucliWebStateAuto: string;
  ucliWebStateOff: string;
  ucliWebFetchOn: string;
  ucliWebFetchOff: string;
  ucliScriptLabel: string;
  ucliScriptDesc: string;
  ucliScriptModeLabel: string;
  ucliScriptModeHint: string;
  ucliScriptOff: string;
  ucliScriptRead: string;
  ucliScriptFull: string;
  tabHintToggle: string;
  tabSettingsGeneral: string;
  tabSettingsModels: string;
  tabSettingsFleet: string;
  tabSettingsLayout: string;
  tabSettingsUsage: string;
  tabDiagStatus: string;
  tabDiagAsk: string;
  tabDiagLog: string;
  usageWarning: string;
  usageCheckBtn: string;
  usageChecking: string;
  usageNotSupported: string;
  usageNoSession: string;
  usageAllBusy: string;
  usageSendFailed: string;
  usageParseFailed: string;
  usageCheckedVia: (name: string) => string;
  contextBtn: string;
  contextChecking: string;
  contextHint: string;
  contextUnsupported: string;
  contextNoTmux: string;
  contextBusy: string;
  contextMasked: string;
  contextSendFailed: string;
  contextParseFailed: string;
  pagePrev: string;
  pageNext: string;
  pageOf: (page: number, total: number) => string;
  groupRunningBadge: string;
  collapseAllBtn: string;
  expandAllBtn: string;
  searchPlaceholder: string;
  searchClear: string;
  noSearchMatches: string;
  tabTeam: string;
  tabSteward: string;
  stewardDesc: string;
  stewardOff: string;
  stewardMode: (mode: string) => string;
  stewardLastTick: (ago: string) => string;
  stewardNoTick: string;
  stewardBrain: string;
  stewardTickBtn: string;
  stewardStatQuestions: string;
  stewardStatIdeas: string;
  stewardStatPending: string;
  stewardStatProjects: string;
  stewardQuestionsTitle: string;
  stewardNoQuestions: string;
  stewardAnswerPlaceholder: string;
  stewardAnswerBtn: string;
  stewardAnswered: string;
  stewardAskTitle: string;
  stewardAskPlaceholder: string;
  stewardAskOptionsPlaceholder: string;
  stewardAskBtn: string;
  stewardProjectsTitle: string;
  stewardNoProjects: string;
  stewardColProject: string;
  stewardColPhase: string;
  stewardColPriority: string;
  stewardColNext: string;
  stewardColVisit: string;
  stewardNever: string;
  stewardIdeasTitle: string;
  stewardNoIdeas: string;
  stewardIdeaPlaceholder: string;
  stewardIdeaAddBtn: string;
  stewardIdeaLater: string;
  stewardIdeaDrop: string;
  stewardRecentTitle: string;
  stewardDry: string;
  orchDesc: string;
  orchLineupTitle: string;
  orchAddSelectedBtn: string;
  orchAddSelectedHint: string;
  orchNoSelectionMsg: string;
  orchSkippedIneligible: (names: string) => string;
  orchLineupEmpty: string;
  orchRemoveBtn: string;
  orchRoleLabel: (role: string) => string;
  orchNeedsWorkerMsg: string;
  orchBriefLabel: string;
  orchHandoffLabel: string;
  orchTaskLabel: string;
  orchTaskPlaceholder: string;
  orchVerdictHintLabel: string;
  orchVerdictHintPlaceholder: string;
  orchTimeoutLabel: string;
  orchRunBtn: string;
  orchStarting: string;
  orchRunConfirm: (names: string[], task: string) => string;
  orchCancelRunBtn: string;
  orchCancelRunConfirm: string;
  orchBackBtn: string;
  orchStatusLabel: (status: string) => string;
  orchResultStatusLabel: (status: string) => string;
  orchOutcomeMethodLabel: (method: string) => string;
  orchFinalLabel: string;
  orchTallyLabel: string;
  orchAbstainedLabel: string;
  orchHistoryTitle: string;
  orchHistoryEmpty: string;
  orchShowMoreBtn: string;
  orchViewBtn: string;
}

/** The phase badge's durations: whole seconds in (the server's clock), "45 sn" / "4 dk" / "1 sa 5 dk". */
function phaseDurTr(s: number): string {
  if (s < 60) return `${s} sn`;
  if (s < 3600) return `${Math.floor(s / 60)} dk`;
  return `${Math.floor(s / 3600)} sa ${Math.floor((s % 3600) / 60)} dk`;
}
function phaseDurEn(s: number): string {
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
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
    busyHint: "çalışıyor (bir turu işliyor)",
    idleHint: "boşta (prompt'ta bekliyor)",
    stoppedWord: "durdu",
    cwdHint: "tıkla: tam yolu göster/gizle",
    requestFailed: "istek başarısız: ",
    empty: "Boş.",
    cancelBtn: "vazgeç",
    tabRunning: "Çalışanlar",
    tabRegistered: "Kayıtlı",
    tabUcli: "ucli",
    tabDisabled: "Devre dışı",
    tabRetired: "Emekli",
    tabHistory: "Geçmiş",
    tabDesktop: "Uzak Masaüstü",
    tabSnapshots: "Snapshotlar",
    tabDiag: "Tanı",
    tabSettings: "Ayarlar",
    desktopDesc: "Makinenin ekran görüntüsünü canlı izle (2 fps). Kapatmayı unutma, açıkken sürekli ekran yakalıyor.",
    desktopStartBtn: "Başlat",
    desktopStopBtn: "Durdur",
    desktopStarting: "başlatılıyor… (ilk seferde derleme birkaç saniye sürebilir)",
    desktopStopping: "durduruluyor…",
    desktopConnecting: "bağlanıyor…",
    desktopWaitingFrame: "ilk görüntü bekleniyor…",
    desktopControlOnBtn: "Kontrolü Al",
    desktopControlOffBtn: "Kontrolü Bırak",
    desktopControlHint: "Kontrol açık: tıklama/scroll/yazı makineye gerçek zamanlı gidiyor — GERÇEK fare/klavyeyle aynı, biri fiziksel olarak kullanıyorsa çakışabilir. Kısayol tuşları (Ctrl/Alt/⌘ kombinasyonları) henüz desteklenmiyor.",
    desktopCursorToggle: "İmleci göster",
    selWord: "seçili",
    selectNeedsHo: "needs-ho seç",
    selectAttention: "dikkat gerekenleri seç",
    selectWindowless: "penceresizleri seç",
    mirrorAllBtn: "uzak pencereleri aç",
    mirrorAllHint:
      "Uzak host'lardaki çalışan oturumların yerel masaüstü (mirror) pencerelerini açar. Seçim varsa yalnız seçilenler, yoksa penceresi açık olmayan tümü. 4'lü gruplarla açılır; zaten açık olanlar tekrar açılmaz.",
    mirrorAllNone: "Açılacak uzak oturum yok (hepsinin penceresi açık ya da uzakta çalışan tmux oturumu yok).",
    mirrorAllConfirm: (names) => `${names.length} uzak oturumun masaüstü penceresi açılsın mı?\n\n${names.join(", ")}`,
    windowlessSelectHint:
      "Ekranda penceresi olmayan (tmux'ta arkada koşan) yerel oturumları seçer. Hiçbir şey durdurmaz: işi bitenleri 'durdur' ile sen kapatırsın. Uzak host'lar dahil değil.",
    windowlessUnknown: "Penceresiz listesi şu an bilinmiyor (tmux yanıt vermedi); hiçbir şey seçilmedi.",
    windowlessNone: "Penceresiz çalışan yerel oturum yok.",
    attentionHint: "boşta olan (meşgul değil) VE AYRICA satır uyarı eşiğine (Ayarlar) ulaşmış olanları seçer — ikisi birden gerekir",
    hoCol: "ho?",
    hoHint: "handover gerekli mi? (repo kirli / untracked / baseline'dan beri commit / RFH yok — sinyallerden biri)",
    hoUnknown: "?",
    stopBtn: "durdur",
    disableBtn: "devre dışı bırak",
    retireBtn: "emekli et",
    resetBtn: "durdur + sıfırdan başlat",
    bulkStartBtn: "başlat",
    handoverBtn: "handover",
    compactBtn: "compact",
    legendStop: "sadece process/pencereyi kapatır — kayıt AKTİF kalır, \"Kayıtlı\" sekmesinden devam ettirilir; instance (↳) ise \"Geçmiş\" sekmesine düşer",
    legendDisable: "durdurur + otomasyon (guard) bir daha AÇMAZ — \"Devre dışı\" sekmesine taşınır, oradan geri alınır; instance'ta (↳) sadece durdurur",
    legendRetire: "durdurur + arşive kaldırır — \"Emekli\" sekmesine taşınır, \"tekrar işe al\" ile döner; instance'ta (↳) sadece durdurur",
    legendReset: "durdurur + roster/varsayılan ayarlarla sıfırdan (--new) yeniden başlatır (elle seçilmiş tek-seferlik bir model/effort korunmaz) — eski konuşma/context atılır, kayıt aktif kalır",
    legendRestart: "çalışıyorsa durdurur, sonra AYNI blueprint'ten YENİ isimle taze bir kayıt başlatır — eski kayıt durur ama konuşması kaybolmaz (Kayıtlı/Geçmiş'te kalır); en sık ihtiyaç duyulan, varsayılan aksiyon",
    legendNewchatBulk: "mevcut kaydı hiç durdurmadan AYNI blueprint'ten AYRI, ek bir yeni chat açar — ikisi birden aynı anda çalışmaya devam eder",
    legendBulkStart: "seçili kayıtlı (durdurulmuş) oturumları varsayılan parametrelerle (kayıtlı/varsayılan model, permission=auto, en yüksek effort, resume — fresh değil) tek tek başlatır",
    legendHandover: "wrap-up mesajı gönderip AYNI geçmişle yeniden açar (kapat+devam) — commit/push + not düşme için",
    legendCompact: "konuşmayı sıkıştırıp (context özetlenir) AYNI geçmişle yeniden açar — sadece claude CLI, birkaç dakika sürebilir",
    bulkConfirm: (label, expl, names) => `${label} — ${expl}\n\nseçili (${names.length}): ${names.join(', ')}\n\nDevam edilsin mi?`,
    bulkSkippedUnreg: "kayıtsız olduğu için atlanacak: ",
    bulkDone: (ok, fail) => `bitti — ${ok} tamam` + (fail ? `, ${fail} hata` : ''),
    optionsBtn: "seçenekler ▾",
    startBtn: "başlat ▾",
    terminalBtn: "terminal",
    remoteTerminalHint: "uzak host terminali henüz desteklenmiyor — bu sürümde sadece local session'lar için çalışır",
    termPlaceholder: "komut yaz — Enter/Gönder yollar, Shift+Enter yeni satır…",
    termMaskedPlaceholder: "gizli girdi (parola?)…",
    termMaskedHint: "🔒 bu pane şu an gizli bir girdi bekliyor (ör. parola) — yazdığınız burada gizlenir",
    termSend: "gönder",
    termLiveLabel: "canlı yazma",
    termLiveHint: "açıkken siyah terminal alanına tıklayıp doğrudan yazabilirsiniz — her tuş (ok tuşları, ctrl-c, Enter dahil) anında CLI'a gider, alttaki kutuya gerek kalmaz. Kapalıyken terminal salt-okunur bir aynadır. Tercih bu tarayıcıda hatırlanır.",
    termLiveOn: "⌨ canlı yazma açık — terminale tıklayıp yazın; tuşlar doğrudan CLI'a gider (yazdıklarınız ~200ms'lik ekran yenilemesinde görünür)",
    termCtrlLabel: "ctrl",
    termCtrlHint: "işaretliyken canlı yazmada bastığınız her harf Ctrl+harf olarak gider (ör. x → Ctrl-X) — fiziksel Ctrl tuşu olmayan dokunmatik klavyeler için. Check/uncheck gibi çalışır: siz kaldırana kadar işaretli kalır (tek basışta kendi kendine kapanmaz). Art arda birden fazla Ctrl+harf göndermek için (ör. Ctrl-X sonra Ctrl-S) işaretli bırakıp ikisini de yazın; aralarına düz bir harf (ör. Ctrl-X sonra düz v) sokmak için harften önce işareti kaldırın.",
    termCtrlOn: "⎈ ctrl işaretli — bastığınız harfler Ctrl+harf olarak gider, siz kaldırana kadar",
    termGone: (err) => `✗ ${err}`,
    termScrolledHint: "⏸ yukarı kaydırdınız — canlı akış duraklatıldı, dibe dönünce devam eder",
    termHistoryBtn: "⇡ geçmiş",
    termHistoryBtnHint: "Önceki çıktıyı (scrollback) yükler; bu sırada canlı akış duraklar. Yukarı kaydırmak da aynısını yapar.",
    termHistoryLoading: "⏳ geçmiş yükleniyor…",
    termLiveBtn: "⇣ canlı",
    termLiveBtnHint: "Geçmişi kapatıp canlı görünüme dön",
    termHistorySize: (size, limit) => `${size}/${limit} satır`,
    termHistorySizeHint: "bu pane'in tmux scrollback'i — limite ulaşınca tmux en eski satırları siler; buraya yaklaşması genelde bir handover için iyi bir işarettir",
    termCopyBtn: "kopyala",
    termCopied: "✓ kopyalandı",
    termCopyHint: "görünen çıktıyı panoya kopyala (mobilde dokunarak seçim güvenilir değil)",
    termModeLabel: "mod",
    termModeHint: "izin modu — seçili görünen, pane'in durum çubuğundan OKUNAN gerçek moddur; değiştirmek CLI'nin Shift+Tab döngüsünü kullanır (birkaç saniye sürebilir). Döngüde olmayan bir mod seçilirse tam tur atılıp başlangıç moduna dönülür, hiçbir şey değişmez; bypassPermissions/dontAsk sadece başlatırken ayarlanabilir",
    termModePick: "mod seç…",
    termModeApplying: "uygulanıyor…",
    termModelLabel: "model",
    termModelHint: "/model komutunu gönderir — CLI kabul etmezse terminalde açılan seçiciden elle seçin. Seçili görünen değer session'ın BAŞLATILDIĞI model (canlı /model değişikliği claude'da geri okunamıyor, sadece siz buradan değiştirirseniz güncellenir).",
    termModelPick: "model seç…",
    termEffortLabel: "effort",
    termEffortHint: "session'ın başlatıldığı effort değeri (komut satırından okundu) — canlı değiştirilemiyor, değiştirmek için session'ı o effort'la yeniden başlatın",
    termOpen: "aç",
    tabTermView: "terminal",
    tabChatView: "sohbet",
    chatModeLast: "son mesaj",
    chatModeFull: "tüm session",
    chatYou: "Sen",
    chatAssistant: "Asistan",
    chatEmpty: "(boş)",
    chatCompacted: "Bağlam sıkıştırıldı (compaction)",
    chatSummary: "Sıkıştırma özeti (aç/kapat)",
    chatUnsupported: "bu CLI için sohbet görünümü henüz yok — terminal sekmesini kullanın",
    chatLoadError: "yüklenemedi: ",
    tabFilesView: "dosyalar",
    tabInfoView: "bilgi",
    viewBtn: "görüntüle",
    readOnlySessionHint: "Bu session çalışmıyor — burada son sohbet ve dosyalar salt-okunur gösteriliyor, terminal yok.",
    filesEmpty: "(boş klasör)",
    filesLoadError: "yüklenemedi: ",
    filesUp: "⬆ yukarı",
    filesDownload: "indir",
    filesView: "görüntüle",
    filesRootLabel: "kök:",
    filesOpenVscode: "VS Code'da Aç",
    filesOpenVscodeHint: "Yeni bir VS Code penceresi açar — sadece fiziksel olarak makinenin başındaysan (veya Uzak Masaüstü'yle görüyorsan) işe yarar, panelden görüntülenemez.",
    filesUpload: "⬆ yükle",
    filesUploadHint: "veya dosyaları buraya sürükleyin",
    filesUploadError: "yükleme başarısız: ",
    filesUploadConfirmOverwrite: "'{name}' zaten var, üzerine yazılsın mı?",
    filesNewFolder: "+ 📁 yeni klasör",
    filesNewFolderPrompt: "yeni klasör adı:",
    filesDelete: "🗑",
    filesDeleteConfirm: "'{name}' silinsin mi? Bu geri alınamaz.",
    filesDeleteConfirmFolder: "'{name}' klasörü İÇİNDEKİ HER ŞEYLE birlikte silinsin mi? Bu geri alınamaz.",
    filesRename: "✏️",
    filesRenamePrompt: "yeni ad:",
    filesEdit: "📝",
    filesSave: "kaydet",
    filesSaveError: "kaydedilemedi: ",
    filesActionError: "işlem başarısız: ",
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
    registerSuccess: (name) => `✓ "${name}" kaydedildi — Kayıtlı listesinde "Başlat"a basın`,
    registerSaving: "kaydediliyor…",
    editBtn: "✎ düzenle",
    editTitle: "isim/klasör/model düzenle",
    editSave: "kaydet",
    editCancel: "vazgeç",
    reactivateBtn: "tekrar işe al + başlat",
    historyDesc:
      "Durdurulmuş instance'lar: bir blueprint'ten 'yeni sohbet' ile açılıp sonra durdurulan tarihli session'lar. " +
      "'Devam ettir' aynı isimle, kaldığı konuşmadan açar; 'Unut' kaydı sadece bu listeden siler, konuşma dosyalarına dokunmaz.",
    historyCount: (count) => `${count} durdurulmuş instance`,
    historyResumeBtn: "devam ettir",
    historyForgetBtn: "unut",
    historyForgetConfirm: (name) => `${name} geçmişten silinsin mi? Konuşma dosyalarına dokunulmaz.`,
    historyNoBlueprint: "(blueprint yok)",
    historyHostError: (host, msg) => `${host}: geçmiş alınamadı (${msg})`,
    instanceBadgeHint: (bp) => `instance: "${bp}" blueprint'inden açıldı`,
    modeResume: "devam ettir",
    modeReset: "sıfırla ve başlat",
    modeNewchat: "yeni chat aç",
    modeRestart: "durdur + yeni isimle başlat",
    modeChoiceNewchatOnly: "Ayrı yeni chat aç (mevcuduna dokunmaz)",
    modeChoiceResume: "Devam ettir (kaldığı yerden)",
    modeChoiceReset: "Bu ismi SIFIRLA (--new, geçmiş bir daha görünmez — nadiren gereken bir seçenek)",
    modeChoiceNewchat: "Ayrı yeni chat aç (yeni isimle, mevcuduna dokunmaz)",
    modeChoiceRestart: "Durdur + YENİ isimle taze başlat (bu kayıt durur ama konuşması kaybolmaz)",
    runningNote: (name) => `⚠ ${name} şu an ÇALIŞIYOR — "Durdur + yeni isimle başlat" onu durdurup YENİ isimle taze bir kayıt açar (bu kayıt durur, konuşması kaybolmaz); "Yeni chat aç" ${name}'a hiç dokunmadan AYRI, ek bir chat açar; "Sıfırla" ise onu durdurup AYNI isimle sıfırdan başlatır (mevcut konuşma bir daha görünmez — nadiren gerekir).`,
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
    usageBadge: (tokens, requests, floor, quota) =>
      `${floor ? "≥" : ""}${tokens} token · ${requests} istek${quota ? ` · kota ≈${quota}` : ""}`,
    usageHint: (u) => {
      const n = (x: number) => x.toLocaleString("tr-TR");
      const cachedPct = u.prompt_tokens > 0 ? ` (%${Math.round((100 * u.cached_tokens) / u.prompt_tokens)})` : "";
      const floor = u.unmetered > 0 || u.reported < u.requests;
      return [
        "Bu ucli sürecinin başından beri (tüm görevler, başarısız olanlar dahil):",
        `istek: ${n(u.requests)}${u.reported < u.requests ? ` (uç nokta yalnız ${n(u.reported)} tanesinin usage'ını bildirdi)` : ""}`,
        `girdi: ${n(u.prompt_tokens)} token, ${n(u.cached_tokens)} tanesi önbellekli${cachedPct}`,
        `çıktı: ${n(u.completion_tokens)} token (bunun ${n(u.reasoning_tokens)} tanesi akıl yürütme)`,
        ...(u.quota_tokens != null
          ? [`kota eşdeğeri: ≈${n(u.quota_tokens)} token (Evren önbellekli girdiyi %3 sayar; hesap kotasına yansıyan budur, ham toplam değil)`]
          : []),
        ...((u.warn ?? 0) > 0
          ? [`⚠ ${(u.warn ?? 0) >= 2 ? "kırmızı" : "amber"} uyarı eşiği aşıldı (Ayarlar > ucli kullanım uyarısı; yalnız renk, hiçbir şey durdurulmaz)`]
          : []),
        ...(u.unmetered > 0
          ? [`cevapsız deneme: ${n(u.unmetered)} (zaman aşımı ya da sunucu hatası; sunucu sayıyor ama tokeni bilinmiyor)`]
          : []),
        ...(floor ? ["≥: gerçek yakım gösterilenden fazla olabilir, az olamaz"] : []),
      ].join("\n");
    },
    pmAllowCreateHint:
      "allow-create: yalnız YENİ dosya yaratır; var olan bir dosyayı değiştiremez, silemez, taşıyamaz. 'Önce iskeleti yaz, sonra doldur' çalışmaz: ikinci yazma reddedilir, raporu tek seferde yazdır.",
    phaseBadge: (p) => {
      const e = p.elapsed ?? null;
      const d = e != null ? ` ${phaseDurTr(e)}` : "";
      const quiet = p.idle != null && p.idle >= 20 ? ` · ${phaseDurTr(p.idle)} sessiz` : "";
      const kib = p.streamed_bytes != null ? ` · ${Math.max(1, Math.round(p.streamed_bytes / 1024))} KiB` : "";
      const tries = p.max_attempts ? ` ${p.attempt ?? 1}/${p.max_attempts}` : "";
      const again = (p.attempt ?? 1) > 1 && p.max_attempts ? ` (${p.attempt}/${p.max_attempts})` : "";
      const left = phaseDurTr(Math.max(0, (p.wait_secs ?? 0) - (e ?? 0)));
      switch (p.name) {
        case "waiting_response":
          return `⏳ yanıt bekliyor${d}${again}`;
        case "thinking":
          return `💭 düşünüyor${d}${kib}${quiet}${again}`;
        case "writing":
          return `✍ yazıyor${d}${kib}${quiet}${again}`;
        case "retry_backoff":
          return `↻ yeniden deneme${tries}, ${left} sonra`;
        case "rate_limited":
          return `⏸ kota sınırı${tries}, ${left} bekliyor`;
        default:
          return `${p.name}${d}`;
      }
    },
    phaseHint: (p) => {
      const what: Record<string, string> = {
        waiting_response: "yanıt bekliyor: istek gönderildi, yanıt henüz gelmedi",
        thinking: "düşünüyor: model akıl yürütme parçalarını akıtıyor",
        writing: "yazıyor: model cevap metnini akıtıyor",
        retry_backoff: "yeniden deneme bekleniyor: son deneme başarısız oldu",
        rate_limited: "kota/hız sınırı (429): ucli bekleyip yeniden deneyecek",
      };
      return [
        "Şu anki model çağrısı (ucli durum dosyası):",
        what[p.name] ?? `bilinmeyen aşama: ${p.name}`,
        ...(p.elapsed != null ? [`bu aşama ${phaseDurTr(p.elapsed)} sürüyor`] : []),
        ...(p.max_attempts ? [`deneme: ${p.attempt ?? 1}/${p.max_attempts}`] : []),
        ...(p.detail ? [`son hata: ${p.detail}`] : []),
        ...(p.streamed_bytes != null ? [`alınan akış: ${Math.round(p.streamed_bytes / 1024)} KiB (ham SSE baytı, token değil)`] : []),
        ...(p.streamed_bytes != null && p.idle != null ? [`son bayt ${phaseDurTr(p.idle)} önce geldi`] : []),
        ...(p.name === "waiting_response"
          ? ["Oturum --stream olmadan çalışıyorsa yanıt tek parça gelir: düşünüyor/yazıyor ayrımı görünmez, yalnız bekleme süresi görünür."]
          : []),
        ...((p.warn ?? 0) > 0
          ? [
              p.name === "waiting_response"
                ? `⚠ ${(p.warn ?? 0) >= 2 ? "kırmızı" : "amber"}: yanıt uzun süredir gelmiyor (ucli'nin istek zaman aşımı varsayılan 600 sn); çağrı takılmış olabilir`
                : p.name === "thinking" || p.name === "writing"
                  ? `⚠ ${(p.warn ?? 0) >= 2 ? "kırmızı" : "amber"}: akış durdu, uzun süredir yeni bayt gelmiyor; bağlantı donmuş olabilir`
                  : "⚠ amber: ucli çağrıyı yeniden deniyor",
              "Yalnız bilgi: hiçbir şey durdurulmaz.",
            ]
          : []),
      ].join("\n");
    },
    cacheDur: (min) => (min <= 60 ? `${min} dk` : min < 2880 ? `${Math.round(min / 60)} sa` : `${Math.round(min / 1440)} g`),
    cacheBadge: (state, dur) => (state === "cold" ? `❄ ${dur}` : state === "expiring" ? "♨ <5 dk" : `♨ ${dur}`),
    cacheHint: (state, age, left) =>
      [
        `İstem önbelleği (1 saatlik): son gerçek model isteği ${age} önce.`,
        state === "cold"
          ? "SOĞUK: bu oturuma yazılan ilk mesaj bağlamın tamamını yeniden yazar (okumadan çok daha pahalı)."
          : `Sıcak: yaklaşık ${left} sonra soğur; soğuyunca bir sonraki mesaj tüm bağlamı yeniden yazar.`,
        "Yalnız izleme: hiçbir şeyi değiştirmez.",
      ].join("\n"),
    openWindowBtn: "pencere aç",
    openingWindow: "pencere açılıyor…",
    mirrorBtn: "masaüstüne aç",
    mirrorBtnHint: (host) =>
      `Bu makinenin masaüstünde canlı, salt-okunur bir terminal penceresi açar ("cops watch"); session "${host}" host'unda çalışmaya devam eder. Zaten açıksa öne getirir.`,
    mirrorStateOpen: "masaüstünde AÇIK: tıklayınca mevcut pencereyi öne getirir",
    mirrorStateClosed: "masaüstünde KAPALI: tıklayınca yeni pencere açar",
    openingMirror: "açılıyor…",
    mirrorOpened: (label) => `masaüstünde açıldı: ${label}`,
    mirrorAlreadyOpen: (label, focused) =>
      focused ? `${label}: zaten açık, öne getirildi` : `${label}: zaten açık (öne getirilemedi, masaüstlerine bak)`,
    diagAskCliLabel: "CLI",
    diagAskQuestionLabel: "ek soru (opsiyonel)",
    diagAskQuestionPlaceholder: "boş bırakılırsa genel teşhis istenir",
    diagAskBtn: "bu CLI ile sor",
    diagAsking: "açılıyor… (~10-20s)",
    diagAskStarted: (name) => `✓ açıldı: ${name} — terminal'de canlı yanıt görünecek`,
    ioFieldMeta: {
      model: { label: "model", placeholder: "deepseek-v4-flash" },
      endpoint: { label: "endpoint (opsiyonel)", placeholder: "boşsa yerel Ollama" },
      api_key: { label: "API anahtarı (opsiyonel, hiçbir yere kaydedilmez)" },
      api_key_env: { label: "API key env adı (opsiyonel)", placeholder: "UCLI_API_KEY" },
    },
    diagUcliHint: "ucli (unified-cli) rust agent'ına doğrudan soru sor — fleet session AÇMAZ, tmux/Terminal yok, cevap burada görünür. TOBEDECIDED#44(b).",
    diagUcliCwdLabel: "proje dizini",
    diagUcliCwdPlaceholder: "ör. /home/fatihyuce/work/projects/...",
    diagUcliNewSession: "— yeni —",
    diagUcliNewSessionNameLabel: "yeni session adı",
    diagUcliPromptLabel: "prompt",
    diagUcliPromptPlaceholder: "ucli'ye ne sormak istiyorsun?",
    diagUcliModelLabel: "model",
    diagUcliEndpointLabel: "endpoint (opsiyonel)",
    diagUcliEndpointPlaceholder: "boşsa yerel Ollama (http://localhost:11434/v1)",
    diagUcliApiKeyLabel: "API anahtarı (opsiyonel, hiçbir yere kaydedilmez)",
    diagUcliSessionLabel: "session adı (opsiyonel)",
    diagUcliSessionPlaceholder: "verilirse turlar arası hatırlar (.ucli/chat/İSİM.jsonl)",
    diagUcliBtn: "ucli'ye sor",
    diagUcliAsking: "soruluyor…",
    diagUcliResult: (answer, rounds, calls) => `${answer}\n\n(${rounds} model turu, ${calls} araç çağrısı)`,
    diagLogTitle: "son diag-log kayıtları",
    diagLogLoading: "yükleniyor…",
    diagRunAfterFail: "Tanı sekmesine geçip spawn sağlık testi çalıştırılsın mı?",
    handoverMsgTitle: "handover metni",
    handoverMsgHint: "handover butonunun gönderdiği wrap-up mesajı, şu an seçili dilde — ayrı bir CLI açmadan kopyalayıp elle yapıştırabilirsiniz",
    protectedBadge: "dikkat",
    protectedHint: "guard'ı ayakta tutuyor — toplu seçimde/işlemde dikkatli olun",
    hostBadgeHint: (host) => `"${host}" host'unda çalışıyor (local değil)`,
    modelLiveDiffersHint: (registered) =>
      `Session şu an bu modelle çalışıyor (canlıda değiştirilmiş ya da tek seferlik açılmış). Kayıtlı/başlatma modeli: ${registered}`,
    hostsUnreachableMsg: (names) => `⚠ ${names.length} host erişilemez: ${names.join(", ")}`,
    hostsTitle: "Uzak host'lar",
    hostsDesc:
      "Başka bir makinede çalışan claudeops panelini buraya bağlayın — o makinenin oturumları yukarıdaki listelere host rozetiyle eklenir.",
    hostNameLabel: "isim",
    hostBaseUrlLabel: "tunnel URL",
    hostTokenLabel: "token",
    hostExtraUrlsLabel: "yedek URL'ler (opsiyonel)",
    hostExtraUrlsHint:
      "virgül/satırla ayrılmış — birincisi (yukarıdaki) çalışmazsa sırayla denenir, çalışan otomatik öne geçer",
    hostAddBtn: "host ekle",
    hostAdding: "ekleniyor…",
    hostSaveBtn: "kaydet",
    hostSaving: "kaydediliyor…",
    hostEditBtn: "düzenle",
    hostCancelEdit: "vazgeç",
    hostTokenKeepHint: "boş bırakırsan mevcut token korunur",
    hostRemoveBtn: "kaldır",
    hostRemoveConfirm: (name) =>
      `"${name}" host'unu kaldır? (o host'taki session'lar etkilenmez, sadece bu panelden bağlantısı kesilir)`,
    hostTestBtn: "şimdi test et",
    hostTesting: "test ediliyor…",
    hostNone: "kayıtlı uzak host yok",
    cliInstallLabel: "CLI kurulumu",
    cliInstallDesc:
      "hiçbiri zaten sistemde yoksa claudeops'un kendi bin dizinine kurar (~/.claude/claudeops/bin — claude/codex/copilot npm --prefix ile, agy resmi antigravity.google kurulum script'iyle --dir bayrağı vererek — hiçbiri gerçek global/sistem kurulumu DEĞİL, sadece bu kullanıcı).",
    cliInstallBtn: "kur",
    cliInstalling: "kuruluyor…",
    cliUpdateBtn: "güncelle",
    cliManagedByUs: "claudeops tarafından kuruldu",
    cliFoundElsewhere: "sistemde zaten var (dokunulmuyor)",
    cliManualOnly: "otomatik kurulum yok, elle:",
    cliInstallHostLabel: "makine",
    cliInstallHostUnreachable: "bu host'a şu an ulaşılamıyor",
    cliInstallHostOutdated: "bu host'un claudeops'u henüz bu özelliği desteklemiyor — orada 'git pull' + servis restart gerekiyor",
    hostConnected: "bağlı",
    hostUnreachable: "erişilemez",
    hostLocalLabel: "bu makine (local)",
    tunnelInfoLabel: "bu makinenin tüneli",
    tunnelNoneMsg: "aktif tünel yok (py/cops service install veya web --tunnel ile başlatın)",
    settingsDesc: "Bu ayarlar sunucu tarafında saklanır (~/.claude/claudeops/settings.json) — telefon dahil hangi cihaz/tarayıcıdan girerseniz girin aynı görünür. Her seçim anında kaydedilir.",
    settingsSingleUserWarning: "⚠ Bu tek-kullanıcılık bir araç: token'ını/tünel URL'ini kimseyle paylaşma — erişen herkes senin CLI session'larını (ve arkalarındaki provider hesabını) sürebilir, çoğu provider'ın kullanım şartları buna izin vermeyebilir.",
    settingsAuto: "(otomatik)",
    settingsAutoModel: (model) => `(otomatik: ${model})`,
    themeLabel: "tema",
    themeSystem: "sistem",
    themeLight: "açık",
    themeDark: "koyu",
    handoverEffortLabel: "handover varsayılan effort",
    handoverEffortHint: "handover (Faz 1/Faz 2/panelin tek-session handover butonu) ile yeniden açılan session'ların effort'u — respawn edilen session'ın BİR SONRAKİ handover'a kadarki ömrü boyunca kalıcı varsayılan olur",
    historyWarnLabel: "satır uyarı eşiği",
    historyWarnHint: "terminal scrollback bu satıra ulaşınca Terminal görünümündeki sayaç vurgulanır ve ana tablonun 'dikkat gerekenleri seç' butonu bu session'ı da seçer — tmux'un sabit 2000 satır limitine yaklaştığını gösterir (o limiti aşınca en eski satırlar silinir)",
    layoutGridLabel: "yerleşim yoğunluğu",
    layoutGridHint: "Yerleşim sekmesinin desktop başına açacağı pencere sayısı: 2 (yan yana iki yarı), 4 (2×2, varsayılan), 8 (4×2, yoğun)",
    fleetSortLabel: "fleet sıralaması",
    fleetSortHint: "Running/Registered/Disabled/Retired tablolarındaki grupların birincil sıralama anahtarı — isme göre (varsayılan, ekranda gördüğün kısa isim) ya da klasör yoluna göre (projenin tam cwd'si — aynı klasördeki session'lar yan yana durur, ama isim klasör adıyla her zaman örtüşmeyebilir)",
    fleetSortByName: "isme göre",
    fleetSortByCwd: "klasör yoluna göre",
    snapshotLabel: "Fleet snapshot",
    snapshotDesc: "çalışan session'ları kaydet, sonra (ör. reboot sonrası) hepsini kayıt anındaki GERÇEK model/effort/izin-modu ile geri aç (açık mirror pencereleri de kaydedilir ve geri açılır)",
    snapshotNone: "henüz kaydedilmiş bir snapshot yok",
    snapshotInfo: (count, when, kind) =>
      `Son snapshot (${kind === "closing" ? "kapanış" : "elle"}): ${when}, ${count} session`,
    snapshotSaveBtn: "Snapshot kaydet",
    snapshotSaving: "Kaydediliyor…",
    snapshotResumeBtn: "Son snapshot'ı geri yükle",
    snapshotResuming: "Geri yükleniyor…",
    snapshotHiddenLabel: "Pencere açmadan (gizli) başlat",
    snapshotResultSummary: (started, alreadyRunning, failed) =>
      `${started} başlatıldı, ${alreadyRunning} zaten çalışıyordu, ${failed} başarısız`,
    snapshotMirrorsSuffix: (mirrors) => (mirrors > 0 ? `, ${mirrors} mirror penceresi` : ""),
    snapshotMirrorResult: (opened, alreadyOpen, failed, skipped) =>
      `mirror pencereleri: ${opened} açıldı, ${alreadyOpen} zaten açıktı, ${failed} başarısız` +
      (skipped > 0 ? `, ${skipped} atlandı (gizli başlatma)` : ""),
    snapshotKindManual: "elle",
    snapshotKindClosing: "kapanış",
    snapshotHistoryLabel: "Geçmiş",
    snapshotHistoryEmpty: "geçmişte başka kayıt yok",
    snapshotHistoryRow: (count, when) => `${when} — ${count} session`,
    snapshotHistoryResumeBtn: "Geri yükle",
    defaultModelLabel: "yeni/resume için varsayılan model (CLI başına)",
    providerBinLabel: "CLI binary yolu override (opsiyonel)",
    providerBinDesc:
      "Bir CLI normal PATH'te bulunamıyorsa (ör. proje-yerel bir kurulum) buraya tam yolunu yazın — boş bırakılırsa normal PATH araması kullanılır. Bu makineye özeldir, paylaşımlı bir PATH konumuna dokunmaz.",
    providerBinPlaceholder: "/tam/yol/binary",
    byokLabel: "API anahtarları (BYOK)",
    byokDesc:
      "Provider'ın kendi bring-your-own-key mekanizmasına geçilecek anahtar. Sadece bu makinede, chmod 600 saklanır; buraya yazdığın değer bir daha hiç geri gösterilmez, sadece \"ayarlı\" durumu görünür.",
    byokSetPlaceholder: "•••• (ayarlı, değiştirmek için yaz)",
    byokEmptyPlaceholder: "henüz ayarlanmadı",
    byokClearBtn: "temizle",
    ucliLimitsLabel: "ucli effort limitleri (max-steps / max-context-kib / max-tool-calls / max-output-tokens)",
    ucliLimitsDesc:
      "ucli'nin medium/high effort preset'lerindeki sayıların üstüne binen override. Boş = preset'in kendi varsayılanı. Birim max-context-kib için KiB'dir, token DEĞİL. max-output-tokens her modele tek bir cevapta izin verilen çıktı uzunluğu — düşükse uzun görevler (ör. derin review) 'kesildi, devam et' turlarıyla adım bütçesini tüketip yarım kalabilir.",
    ucliLimitsMaxStepsLabel: "max-steps",
    ucliLimitsMaxContextKibLabel: "max-context-kib (KiB)",
    ucliLimitsMaxToolCallsLabel: "max-tool-calls",
    ucliLimitsMaxOutputTokensLabel: "max-output-tokens",
    ucliLimitsPlaceholderAuto: "boş = preset varsayılanı",
    ucliLimitsReasoningLabel: "akıl yürütme (--effort)",
    ucliLimitsReasoningHint:
      "ucli'ye --effort olarak geçen düzey (düşünme miktarı). Otomatik: oturumun effort'u (medium/high) aynı adla geçer. Kapalı: bayrak hiç geçmez (eski davranış). Model alanı kabul etmiyorsa (Evren yeteneklerinden okunur, ör. gemma-4-31b) hangi ayar seçilirse seçilsin geçmez. Yalnız YENİ açılan oturumlara uygulanır.",
    ucliLimitsReasoningAuto: "otomatik (oturumun effort'u)",
    ucliLimitsReasoningOff: "kapalı (bayrak yok)",
    ucliLimitsStreamLabel: "yanıt akışı (--stream)",
    ucliLimitsStreamHint:
      "Varsayılan AÇIK. Açıkken model yanıtı akışlı istenir: ucli'nin durum dosyasında ve satırdaki rozette 'düşünüyor' / 'yazıyor' aşamaları ve akan miktar görünür (akış donarsa rozet uyarır), metin terminale canlı basılır. Bedeli: (1) cevap terminalde iki kez görünür (canlı akış, sonra son çıktı); (2) akış yarıda kesilirse (ağ kesintisi) çağrı yeniden DENENMEZ ve görev hata verir, akışsız çağrıda kesinti yanıt gelmeden olursa yeniden denenir. Yalnız YENİ açılan oturumlara uygulanır.",
    ucliLimitsStreamOff: "kapalı",
    ucliLimitsStreamOn: "açık (varsayılan)",
    ucliUsageWarnLabel: "ucli kullanım uyarısı (oturum başına kota eşdeğeri token)",
    ucliUsageWarnDesc:
      "Token rozeti bu eşiklere göre amber/kırmızıya döner. Sayı, Evren hesap kotasına yansıyan değerdir (önbellekli girdi %3 sayılır), ham toplam DEĞİL; süreç başından beri biriken oturum toplamıdır. Yalnız renk: hiçbir şey durdurulmaz. Boş = varsayılan, off ya da 0 = o kademe kapalı.",
    ucliUsageWarnAmberLabel: "amber eşiği",
    ucliUsageWarnRedLabel: "kırmızı eşiği",
    ucliUsageWarnPlaceholder: (def) => `boş = ${def}`,
    tunnelWatchLabel: "tünel sağlık bekçisi",
    tunnelWatchHint:
      "Genel tünel adresi art arda 3 dakika boyunca HTTP 530 verirse (tünel Cloudflare'den koptu ama servis 'active' görünüyor) cloudflared yeniden başlatılır: adres DEĞİŞİR ve ntfy bildirimi gider. Kapalıyken tünel kopunca elle yeniden başlatmak gerekir. Değişiklik en geç 1 dakikada, tüneli yeniden başlatmadan geçerli olur. Yalnız quick tunnel'da çalışır (named tunnel'da yok).",
    tunnelWatchOn: "açık (önerilen)",
    tunnelWatchOff: "kapalı",
    defaultEffortLabel: "yeni oturum için varsayılan effort (CLI başına)",
    routingGuidanceLabel: "işe göre model/effort yönergesi",
    routingGuidanceDesc:
      "Yeni açılan oturumlara 'düşük başla, işe göre alt ajan/model seç' yönergesi eklenir (claude: her açılışta sistem istemine; codex: ~/.codex/AGENTS.md, agy: ~/.gemini/GEMINI.md içinde işaretli blok). Açık oturumlar yeniden açılana kadar etkilenmez. Metni boş bırakırsan paketlenmiş varsayılan kullanılır. copilot için küresel dosya yolu henüz doğrulanamadı (hesap kotası dolu).",
    routingGuidancePlaceholder: "boş = paketlenmiş varsayılan metin (data/routing.md)",
    ucliWebLabel: "ucli web araçları (arama / sayfa getirme)",
    ucliWebDesc:
      "Yalnız claudeops'tan YENİ açılan ucli oturumlarına uygulanır; çalışanlar eski ayarla sürer, panel yeniden başlatması gerekmez. Arama varsayılan AÇIK: adres boşsa claudeops'un yönettiği yerel SearXNG kullanılır (docker kapsayıcısı, yalnız bu makineden erişilir; ucli aramayı kendi içine alınca bu geçici köprü kalkacak). Sayfa getirme (fetch_url) varsayılan KAPALI; yalnız aşağıya yazılan alan adlarına açılır.",
    ucliWebSearchUrlLabel: "arama adresi (SearXNG)",
    ucliWebSearchUrlPlaceholder: "boş = otomatik yerel SearXNG",
    ucliWebSearchUrlHint:
      "SearXNG adresi, örn. http://127.0.0.1:8888/search. Dolu ise o kazanır ve docker'a dokunulmaz. Geçersiz bir adres aramayı KAPALI bırakır, başka yere yönlendirmez.",
    ucliWebDockerLabel: "otomatik yerel arama (docker)",
    ucliWebDockerHint:
      "Arama adresi boşken, ucli oturumu açılırken claudeops'un yönettiği SearXNG kapsayıcısı kurulur ya da başlatılır. Arama adresi doluysa bu seçenek kullanılmaz.",
    ucliWebDockerAuto: "açık (varsayılan)",
    ucliWebDockerOff: "kapalı",
    ucliWebFetchLabel: "sayfa getirme için izinli alan adları",
    ucliWebFetchPlaceholder: "boş = fetch_url kapalı, örn. en.wikipedia.org, docs.rs",
    ucliWebFetchHint:
      "Virgül ya da boşlukla ayrılmış TAM alan adları (joker yok). ucli yalnız bunlara giden HTTP(S) GET isteklerine izin verir.",
    ucliWebStateUrl: (url) => `Arama: ${url}`,
    ucliWebStateUrlInvalid: "Arama: adres geçersiz, KAPALI kalır (http:// ya da https:// ile başlamalı)",
    ucliWebStateAuto: "Arama: otomatik yerel SearXNG (docker)",
    ucliWebStateOff: "Arama: kapalı",
    ucliWebFetchOn: "Sayfa getirme: yazılan alan adlarına açık",
    ucliWebFetchOff: "Sayfa getirme: kapalı",
    ucliScriptLabel: "ucli betik katmanı (Lua)",
    ucliScriptDesc:
      "Model tek bir kısa Lua programı yazar; ucli bunu kendi süreci içinde çalıştırıp araçları o programdan çağırır, modele yalnız programın döndürdüğü küçük değer gider. Yalnız claudeops'tan YENİ açılan ucli oturumlarına uygulanır; çalışanlar eski ayarla sürer. Varsayılan KAPALI: token kazancı henüz kontrollü ölçümle gösterilmedi, kanıtlanmış değeri mekanik işte doğruluk (ör. harf sayma). Betik içindeki her araç çağrısı, yukarıdaki max-tool-calls bütçesine ayrı sayılır.",
    ucliScriptModeLabel: "betik modu (--allow-script)",
    ucliScriptModeHint:
      "Salt-okuma: betik yalnız salt-okuma araçlarını çağırabilir. Tam: betik, oturumun modele zaten verdiği HER şeyi çağırabilir (yazma yalnız oturum yazma izniyle açıldıysa; ayrıca fetch_url, web_search ve MCP araçları). Kapılar modelin kendi çağrılarıyla aynıdır, betik fazladan yetki kazanmaz. Kurulu ucli ikilisi bayrağı tanımıyorsa sessizce atlanır (tanılama günlüğüne yazılır).",
    ucliScriptOff: "kapalı (varsayılan)",
    ucliScriptRead: "salt-okuma (read)",
    ucliScriptFull: "tam (full)",
    tabHintToggle: "Açıklamayı göster/gizle",
    tabSettingsGeneral: "genel",
    tabSettingsModels: "model",
    tabSettingsFleet: "fleet",
    tabSettingsLayout: "layout",
    tabSettingsUsage: "kullanım",
    tabDiagStatus: "durum",
    tabDiagAsk: "sor",
    tabDiagLog: "log",
    usageWarning:
      "⚠ Kontrol, o CLI'nin ÇALIŞAN bir session'ına gerçekten `/usage` yazıp ekranını anlık değiştirir (kimse izlemiyorsa öncelik verilir) — otomatik/sürekli çalışmaz, sadece bastığında.",
    usageCheckBtn: "Kullanımı kontrol et",
    usageChecking: "kontrol ediliyor…",
    usageNotSupported: "desteklenmiyor",
    usageNoSession: "çalışan session yok",
    usageAllBusy: "çalışan session'ların hepsi meşgul/parola bekliyor, şu an kontrol edilemedi",
    usageSendFailed: "komut gönderilemedi",
    usageParseFailed: "yanıt okunamadı",
    usageCheckedVia: (name) => `${name} üzerinden`,
    contextBtn: "Bağlamı kontrol et",
    contextChecking: "kontrol ediliyor…",
    contextHint: "bu session'ın context-window doluluğunu görmek için /context enjekte eder (session meşgulse/parola bekliyorsa çalışmaz)",
    contextUnsupported: "bu CLI için desteklenmiyor",
    contextNoTmux: "bu session tmux üzerinde çalışmıyor",
    contextBusy: "session şu an meşgul, kontrol edilemedi",
    contextMasked: "session parola/gizli girdi bekliyor, kontrol edilemedi",
    contextSendFailed: "komut gönderilemedi",
    contextParseFailed: "yanıt okunamadı",
    pagePrev: "önceki",
    pageNext: "sonraki",
    pageOf: (page, total) => `sayfa ${page}/${total}`,
    groupRunningBadge: "bu grupta çalışan var",
    collapseAllBtn: "hepsini kapat",
    expandAllBtn: "hepsini aç",
    searchPlaceholder: "isim veya cwd ara…",
    searchClear: "aramayı temizle",
    noSearchMatches: "Aramayla eşleşen yok.",
    tabTeam: "Ekip",
    tabSteward: "Değnekçi",
    stewardDesc: "Değnekçi projeleri gezen zamanlayıcı: açık soruları buradan (ya da telefondaki /q bağlantısından) cevaplarsınız, cevap bir sonraki tick'te ilgili oturuma gider. Projeler ve fikir kutusu py/cops steward ile aynı veridir.",
    stewardOff: "Döngü kapalı (steward.enabled) — kayıtlar görülebilir, kendiliğinden tick atılmaz; \"tick\" düğmesi yine çalışır.",
    stewardMode: (mode) => (mode === "observe" ? "mod: observe (oturuma dokunan eylemler yalnız kaydedilir)" : `mod: ${mode}`),
    stewardLastTick: (ago) => `son tick ${ago}`,
    stewardNoTick: "henüz tick yok",
    stewardBrain: "beyin",
    stewardTickBtn: "tick",
    stewardStatQuestions: "açık soru",
    stewardStatIdeas: "yeni fikir",
    stewardStatPending: "bekleyen madde",
    stewardStatProjects: "proje",
    stewardQuestionsTitle: "Sorular",
    stewardNoQuestions: "Açık soru yok.",
    stewardAnswerPlaceholder: "cevap… (seçenekli soruda numara da olur)",
    stewardAnswerBtn: "Cevapla",
    stewardAnswered: "cevaplandı",
    stewardAskTitle: "Soru aç (kendine/beyne not gibi; telefona da gider)",
    stewardAskPlaceholder: "soru metni",
    stewardAskOptionsPlaceholder: "seçenekler, virgülle (isteğe bağlı): evet, hayır, sonra",
    stewardAskBtn: "Sor",
    stewardProjectsTitle: "Projeler",
    stewardNoProjects: "Değnekçi projesi yok — py/cops steward import roster'dakileri alır.",
    stewardColProject: "proje",
    stewardColPhase: "faz",
    stewardColPriority: "öncelik",
    stewardColNext: "sıradaki adım (kart)",
    stewardColVisit: "son uğrama",
    stewardNever: "hiç",
    stewardIdeasTitle: "Fikir kutusu",
    stewardNoIdeas: "Yeni fikir yok.",
    stewardIdeaPlaceholder: "fikir…",
    stewardIdeaAddBtn: "Ekle",
    stewardIdeaLater: "sonra",
    stewardIdeaDrop: "vazgeç",
    stewardRecentTitle: "Son eylemler",
    stewardDry: "kuru",
    orchDesc: "Birden fazla session'a aynı görevi verip yanıtları karşılaştırın. Opsiyonel bir kontrolcü göreve önce kendi brief'ini yazabilir; opsiyonel bir karar verici işçilerin yanıtlarını görüp son kararı verebilir — hiçbiri atanmazsa sonuç işçiler arasındaki çoğunluk oyuyla belirlenir. Bitince kontrolcüye sonuç mesajı gönderilir.",
    orchLineupTitle: "Kadro",
    orchAddSelectedBtn: "Seçilenleri ekle",
    orchAddSelectedHint: "Çalışanlar sekmesinde işaretlediğiniz session'ları (çalışan + local + konuşması olan) kadroya işçi olarak ekler",
    orchNoSelectionMsg: "Önce Çalışanlar sekmesinden en az bir session işaretleyin.",
    orchSkippedIneligible: (names) => `uygun olmadığı için atlandı: ${names}`,
    orchLineupEmpty: "Kadro boş — Çalışanlar sekmesinden session işaretleyip \"Seçilenleri ekle\"ye basın.",
    orchRemoveBtn: "kaldır",
    orchRoleLabel: (role) => {
      const m: Record<string, string> = { worker: "işçi", controller: "kontrolcü", decider: "karar verici" };
      return m[role] ?? role;
    },
    orchNeedsWorkerMsg: "en az bir \"işçi\" rolünde katılımcı gerekli",
    orchBriefLabel: "Brief (kontrolcü tarafından yazıldı, işçilere bu gönderildi)",
    orchHandoffLabel: "kontrolcüye gönderilen sonuç mesajı",
    orchTaskLabel: "Görev",
    orchTaskPlaceholder: "İşçilere ne sorulacak/ne yaptırılacak…",
    orchVerdictHintLabel: "verdict format ipucu (opsiyonel)",
    orchVerdictHintPlaceholder: "ör. sadece evet ya da hayır cevap ver",
    orchTimeoutLabel: "işçi zaman aşımı (sn)",
    orchRunBtn: "Takım olarak çalıştır",
    orchStarting: "başlatılıyor…",
    orchRunConfirm: (names, task) => `Şu session'lara mesaj gönderilecek: ${names.join(", ")}\n\nGörev: ${task}\n\nDevam edilsin mi?`,
    orchCancelRunBtn: "run'ı iptal et",
    orchCancelRunConfirm: "Run iptal edilsin mi? (zaten gönderilmiş mesajlar geri alınamaz, sadece bekleme durur)",
    orchBackBtn: "◀ geri",
    orchStatusLabel: (status) => {
      const m: Record<string, string> = {
        briefing: "brief yazılıyor", working: "çalışıyor", deciding: "karar veriliyor",
        done: "tamamlandı", needs_human: "karar gerekiyor", failed: "hata", cancelled: "iptal edildi",
      };
      return m[status] ?? status;
    },
    orchResultStatusLabel: (status) => {
      const m: Record<string, string> = { ok: "tamam", timeout: "zaman aşımı", cancelled: "iptal edildi", send_failed: "gönderilemedi", no_envelope: "format hatası", unreachable: "erişilemez", pending: "bekleniyor" };
      return m[status] ?? status;
    },
    orchOutcomeMethodLabel: (method) => {
      const m: Record<string, string> = { decider: "karar verici", unanimous: "oybirliği", majority: "çoğunluk", single_worker: "tek işçi", no_consensus: "uzlaşı yok", none: "sonuç yok" };
      return m[method] ?? method;
    },
    orchFinalLabel: "Sonuç",
    orchTallyLabel: "Oylar",
    orchAbstainedLabel: "Çekimser",
    orchHistoryTitle: "Geçmiş run'lar",
    orchHistoryEmpty: "Henüz hiç run çalıştırılmadı.",
    orchShowMoreBtn: "daha fazla göster",
    orchViewBtn: "görüntüle",
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
    busyHint: "busy (working on a turn)",
    idleHint: "idle (waiting at the prompt)",
    stoppedWord: "stopped",
    cwdHint: "click: show/hide full path",
    requestFailed: "request failed: ",
    empty: "Empty.",
    cancelBtn: "cancel",
    tabRunning: "Running",
    tabRegistered: "Registered",
    tabUcli: "ucli",
    tabDisabled: "Disabled",
    tabRetired: "Retired",
    tabHistory: "History",
    tabDesktop: "Remote Desktop",
    tabSnapshots: "Snapshots",
    tabDiag: "Diagnostics",
    tabSettings: "Settings",
    desktopDesc: "Watch the machine's screen live (2 fps). Remember to stop it — it captures the screen continuously while running.",
    desktopStartBtn: "Start",
    desktopStopBtn: "Stop",
    desktopStarting: "starting… (first run may take a few seconds to compile)",
    desktopStopping: "stopping…",
    desktopConnecting: "connecting…",
    desktopWaitingFrame: "waiting for first frame…",
    desktopControlOnBtn: "Take Control",
    desktopControlOffBtn: "Release Control",
    desktopControlHint: "Control is on: clicks/scroll/typing go to the machine in real time — this is the SAME mouse/keyboard as the physical one, it can collide if someone's using it in person. Keyboard shortcuts (Ctrl/Alt/⌘ combos) aren't supported yet.",
    desktopCursorToggle: "Show cursor",
    selWord: "selected",
    selectNeedsHo: "select needs-ho",
    selectAttention: "select needs attention",
    selectWindowless: "select windowless",
    mirrorAllBtn: "open remote windows",
    mirrorAllHint:
      "Opens local desktop (mirror) windows for the running sessions on remote hosts. Only the selected ones if any are selected, otherwise every one without an open window. Opened in groups of 4; already-open windows are not opened again.",
    mirrorAllNone: "Nothing to open (every remote session already has a window, or no remote tmux session is running).",
    mirrorAllConfirm: (names) => `Open desktop windows for ${names.length} remote sessions?\n\n${names.join(", ")}`,
    windowlessSelectHint:
      "Selects local sessions with no screen window (running in the background in tmux). Stops nothing: close the finished ones with 'stop' yourself. Remote hosts are not included.",
    windowlessUnknown: "The windowless list is unknown right now (tmux did not answer); nothing was selected.",
    windowlessNone: "No local session is running windowless.",
    attentionHint: "selects sessions that are idle (not busy) AND have reached the line warn threshold (Settings) — both required",
    hoCol: "ho?",
    hoHint: "needs handover? (dirty repo / untracked / commits since baseline / no RFH — any one signal)",
    hoUnknown: "?",
    stopBtn: "stop",
    disableBtn: "disable",
    retireBtn: "retire",
    resetBtn: "stop + restart fresh",
    bulkStartBtn: "start",
    handoverBtn: "handover",
    compactBtn: "compact",
    legendStop: "kills only the process/window — stays REGISTERED, resume it from the \"Registered\" tab; an instance (↳) goes to the \"History\" tab",
    legendDisable: "stop + automation (guard) will NOT reopen it — moves to the \"Disabled\" tab, reversible there; on an instance (↳) it just stops it",
    legendRetire: "stop + archive — moves to the \"Retired\" tab, comes back via \"reactivate\"; on an instance (↳) it just stops it",
    legendReset: "stops it, then restarts it fresh (--new) with the roster/default settings (a one-off manually-picked model/effort is NOT preserved) — drops the old conversation/context, keeps the registration active",
    legendRestart: "stops it if running, then starts a fresh record under a NEW name from the same blueprint — the old record stops but its conversation isn't lost (stays in Registered/History); the most commonly needed, default action",
    legendNewchatBulk: "opens a separate, additional new chat from the same blueprint WITHOUT stopping the existing record — both keep running at once",
    legendBulkStart: "starts each selected registered (stopped) session one by one with default parameters (roster/default model, permission=auto, highest effort, resume — not fresh)",
    legendHandover: "sends a wrap-up prompt and reopens with the SAME history (close+continue) — for commit/push + notes",
    legendCompact: "compacts the conversation (summarizes context) and reopens with the SAME history — claude CLI only, can take a few minutes",
    bulkConfirm: (label, expl, names) => `${label} — ${expl}\n\nselected (${names.length}): ${names.join(', ')}\n\nProceed?`,
    bulkSkippedUnreg: "skipped (unregistered): ",
    bulkDone: (ok, fail) => `done — ${ok} ok` + (fail ? `, ${fail} failed` : ''),
    optionsBtn: "options ▾",
    startBtn: "start ▾",
    terminalBtn: "terminal",
    remoteTerminalHint: "remote host terminal not supported yet — this build only works for local sessions",
    termPlaceholder: "type a command — Enter/Send submits, Shift+Enter adds a newline…",
    termMaskedPlaceholder: "hidden input (password?)…",
    termMaskedHint: "🔒 this pane is currently waiting for hidden input (e.g. a password) — what you type here is masked",
    termSend: "send",
    termLiveLabel: "live typing",
    termLiveHint: "when on, click the black terminal area and type straight into it — every key (arrows, ctrl-c, Enter included) goes to the CLI immediately, no need for the box below. When off, the terminal is a read-only mirror. The choice is remembered in this browser.",
    termLiveOn: "⌨ live typing on — click the terminal and type; keys go straight to the CLI (what you type shows up on the next ~200ms screen refresh)",
    termCtrlLabel: "ctrl",
    termCtrlHint: "while checked, every letter key you press in live typing is sent as Ctrl+letter (e.g. x → Ctrl-X) — for touch keyboards with no physical Ctrl key. It works like a check/uncheck toggle: it stays checked until YOU uncheck it (it does not auto-release after one key). To send several Ctrl+letters in a row (e.g. Ctrl-X then Ctrl-S), leave it checked for both; to follow with a plain letter instead (e.g. Ctrl-X then a bare v), uncheck it first.",
    termCtrlOn: "⎈ ctrl armed — letters you press go out as Ctrl+letter until you uncheck it",
    termGone: (err) => `✗ ${err}`,
    termScrolledHint: "⏸ scrolled up — live updates paused, resumes when you scroll back to bottom",
    termHistoryBtn: "⇡ history",
    termHistoryBtnHint: "Loads earlier output (scrollback); live updates pause meanwhile. Scrolling up does the same.",
    termHistoryLoading: "⏳ loading history…",
    termLiveBtn: "⇣ live",
    termLiveBtnHint: "Close the history and go back to the live view",
    termHistorySize: (size, limit) => `${size}/${limit} lines`,
    termHistorySizeHint: "this pane's tmux scrollback — once it hits the limit, tmux drops the oldest lines; getting close is usually a good sign it's time for a handover",
    termCopyBtn: "copy",
    termCopied: "✓ copied",
    termCopyHint: "copy visible output to clipboard (touch-selection is unreliable on mobile)",
    termModeLabel: "mode",
    termModeHint: "permission mode — the selected value is the real one, READ from the pane's status bar; changing it drives the CLI's own Shift+Tab cycle (can take a few seconds). A mode that isn't in this session's cycle leaves it untouched (full loop, back to where it started); bypassPermissions/dontAsk are only settable at session start",
    termModePick: "pick mode…",
    termModeApplying: "applying…",
    termModelLabel: "model",
    termModelHint: "sends the /model command — if the CLI doesn't accept the argument, finish the pick in the picker that opens in the terminal. The value shown is the model the session was STARTED with (claude gives no way to read a live /model change back; it only updates when you switch it from here).",
    termModelPick: "pick model…",
    termEffortLabel: "effort",
    termEffortHint: "the effort the session was started with (read from its command line) — not live-changeable, restart the session with a different one to change it",
    termOpen: "open",
    tabTermView: "terminal",
    tabChatView: "chat",
    chatModeLast: "last message",
    chatModeFull: "full session",
    chatYou: "You",
    chatAssistant: "Assistant",
    chatEmpty: "(empty)",
    chatCompacted: "Context compacted",
    chatSummary: "Compaction summary (toggle)",
    chatUnsupported: "chat view isn't available for this CLI yet — use the terminal tab",
    chatLoadError: "failed to load: ",
    tabFilesView: "files",
    tabInfoView: "info",
    viewBtn: "view",
    readOnlySessionHint: "This session isn't running — showing its last chat and files read-only, no terminal.",
    filesEmpty: "(empty folder)",
    filesLoadError: "failed to load: ",
    filesUp: "⬆ up",
    filesDownload: "download",
    filesView: "view",
    filesRootLabel: "root:",
    filesOpenVscode: "Open in VS Code",
    filesOpenVscodeHint: "Opens a new VS Code window — only useful physically at the machine (or viewing it via Uzak Masaüstü), can't be shown in this panel.",
    filesUpload: "⬆ upload",
    filesUploadHint: "or drag files here",
    filesUploadError: "upload failed: ",
    filesUploadConfirmOverwrite: "'{name}' already exists, overwrite?",
    filesNewFolder: "+ 📁 new folder",
    filesNewFolderPrompt: "new folder name:",
    filesDelete: "🗑",
    filesDeleteConfirm: "Delete '{name}'? This can't be undone.",
    filesDeleteConfirmFolder: "Delete the folder '{name}' AND EVERYTHING IN IT? This can't be undone.",
    filesRename: "✏️",
    filesRenamePrompt: "new name:",
    filesEdit: "📝",
    filesSave: "save",
    filesSaveError: "failed to save: ",
    filesActionError: "action failed: ",
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
    registerSuccess: (name) => `✓ "${name}" registered — click "Start" on it in the Registered list`,
    registerSaving: "saving…",
    editBtn: "✎ edit",
    editTitle: "edit name/folder/model",
    editSave: "save",
    editCancel: "cancel",
    reactivateBtn: "reactivate + start",
    historyDesc:
      "Stopped instances: dated sessions opened from a blueprint via 'new chat' and later stopped. " +
      "'Resume' reopens one under the same name, continuing its conversation; 'Forget' only removes it from this list and never touches the conversation files.",
    historyCount: (count) => `${count} stopped instance${count === 1 ? "" : "s"}`,
    historyResumeBtn: "resume",
    historyForgetBtn: "forget",
    historyForgetConfirm: (name) => `Remove ${name} from history? Conversation files are not touched.`,
    historyNoBlueprint: "(no blueprint)",
    historyHostError: (host, msg) => `${host}: couldn't load history (${msg})`,
    instanceBadgeHint: (bp) => `instance: opened from blueprint "${bp}"`,
    modeResume: "resume",
    modeReset: "reset and start",
    modeNewchat: "start new chat",
    modeRestart: "stop + start under new name",
    modeChoiceNewchatOnly: "Start a separate new chat (does not touch the existing one)",
    modeChoiceResume: "Resume (from where it left off)",
    modeChoiceReset: "RESET this name (--new, previous history no longer shown — rarely what you want)",
    modeChoiceNewchat: "Start a separate new chat (new name, does not touch the existing one)",
    modeChoiceRestart: "Stop + start fresh under a NEW name (old record stops but its conversation isn't lost)",
    runningNote: (name) => `⚠ ${name} is currently RUNNING — "Stop + start under new name" stops it and opens a fresh record under a NEW name (the old record stops but its conversation isn't lost); "Start new chat" opens a SEPARATE extra chat without touching ${name}; "Reset" stops it and restarts fresh under the SAME name (its conversation won't be shown again — rarely what you want).`,
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
    usageBadge: (tokens, requests, floor, quota) =>
      `${floor ? "≥" : ""}${tokens} tokens · ${requests} req${quota ? ` · quota ≈${quota}` : ""}`,
    usageHint: (u) => {
      const n = (x: number) => x.toLocaleString("en-US");
      const cachedPct = u.prompt_tokens > 0 ? ` (${Math.round((100 * u.cached_tokens) / u.prompt_tokens)}%)` : "";
      const floor = u.unmetered > 0 || u.reported < u.requests;
      return [
        "Since this ucli process started (all tasks, failed ones included):",
        `requests: ${n(u.requests)}${u.reported < u.requests ? ` (the endpoint reported usage for only ${n(u.reported)})` : ""}`,
        `input: ${n(u.prompt_tokens)} tokens, ${n(u.cached_tokens)} of them cached${cachedPct}`,
        `output: ${n(u.completion_tokens)} tokens (${n(u.reasoning_tokens)} of them reasoning)`,
        ...(u.quota_tokens != null
          ? [`quota equivalent: ≈${n(u.quota_tokens)} tokens (Evren counts cached input at 3%; this is what hits the account quota, not the raw total)`]
          : []),
        ...((u.warn ?? 0) > 0
          ? [`⚠ ${(u.warn ?? 0) >= 2 ? "red" : "amber"} warning threshold exceeded (Settings > ucli usage warning; colour only, nothing is stopped)`]
          : []),
        ...(u.unmetered > 0
          ? [`unanswered attempts: ${n(u.unmetered)} (timeout or server error; the server counts them but their tokens are unknown)`]
          : []),
        ...(floor ? ["≥: the real burn may be higher than shown, never lower"] : []),
      ].join("\n");
    },
    pmAllowCreateHint:
      "allow-create: only creates NEW files; it cannot modify, delete or move an existing one. 'Write a skeleton first, fill it in later' does not work: the second write is refused, have the report written in one go.",
    phaseBadge: (p) => {
      const e = p.elapsed ?? null;
      const d = e != null ? ` ${phaseDurEn(e)}` : "";
      const quiet = p.idle != null && p.idle >= 20 ? ` · quiet ${phaseDurEn(p.idle)}` : "";
      const kib = p.streamed_bytes != null ? ` · ${Math.max(1, Math.round(p.streamed_bytes / 1024))} KiB` : "";
      const tries = p.max_attempts ? ` ${p.attempt ?? 1}/${p.max_attempts}` : "";
      const again = (p.attempt ?? 1) > 1 && p.max_attempts ? ` (${p.attempt}/${p.max_attempts})` : "";
      const left = phaseDurEn(Math.max(0, (p.wait_secs ?? 0) - (e ?? 0)));
      switch (p.name) {
        case "waiting_response":
          return `⏳ waiting for response${d}${again}`;
        case "thinking":
          return `💭 thinking${d}${kib}${quiet}${again}`;
        case "writing":
          return `✍ writing${d}${kib}${quiet}${again}`;
        case "retry_backoff":
          return `↻ retry${tries} in ${left}`;
        case "rate_limited":
          return `⏸ rate limited${tries}, waiting ${left}`;
        default:
          return `${p.name}${d}`;
      }
    },
    phaseHint: (p) => {
      const what: Record<string, string> = {
        waiting_response: "waiting for response: the request was sent, no answer yet",
        thinking: "thinking: the model is streaming reasoning chunks",
        writing: "writing: the model is streaming its answer text",
        retry_backoff: "waiting to retry: the last attempt failed",
        rate_limited: "rate limited (429): ucli will wait and retry",
      };
      return [
        "Current model call (ucli status file):",
        what[p.name] ?? `unknown phase: ${p.name}`,
        ...(p.elapsed != null ? [`this phase has lasted ${phaseDurEn(p.elapsed)}`] : []),
        ...(p.max_attempts ? [`attempt: ${p.attempt ?? 1}/${p.max_attempts}`] : []),
        ...(p.detail ? [`last error: ${p.detail}`] : []),
        ...(p.streamed_bytes != null ? [`streamed so far: ${Math.round(p.streamed_bytes / 1024)} KiB (raw SSE bytes, not tokens)`] : []),
        ...(p.streamed_bytes != null && p.idle != null ? [`last bytes arrived ${phaseDurEn(p.idle)} ago`] : []),
        ...(p.name === "waiting_response"
          ? ["A session running without --stream gets its answer in one piece: the thinking/writing split is not visible, only the wait."]
          : []),
        ...((p.warn ?? 0) > 0
          ? [
              p.name === "waiting_response"
                ? `⚠ ${(p.warn ?? 0) >= 2 ? "red" : "amber"}: no response for a long time (ucli's request timeout defaults to 600 s); the call may be stuck`
                : p.name === "thinking" || p.name === "writing"
                  ? `⚠ ${(p.warn ?? 0) >= 2 ? "red" : "amber"}: the stream stopped, no new bytes for a long time; the connection may be frozen`
                  : "⚠ amber: ucli is retrying the call",
              "Information only: nothing is stopped.",
            ]
          : []),
      ].join("\n");
    },
    cacheDur: (min) => (min <= 60 ? `${min}m` : min < 2880 ? `${Math.round(min / 60)}h` : `${Math.round(min / 1440)}d`),
    cacheBadge: (state, dur) => (state === "cold" ? `❄ ${dur}` : state === "expiring" ? "♨ <5m" : `♨ ${dur}`),
    cacheHint: (state, age, left) =>
      [
        `Prompt cache (1 hour): the last real model request was ${age} ago.`,
        state === "cold"
          ? "COLD: the first message sent to this session rewrites the whole context (far pricier than a read)."
          : `Warm: goes cold in about ${left}; once cold, the next message rewrites the whole context.`,
        "Monitoring only: it changes nothing.",
      ].join("\n"),
    openWindowBtn: "open window",
    openingWindow: "opening window…",
    mirrorBtn: "open on desktop",
    mirrorBtnHint: (host) =>
      `Opens a live, read-only terminal window on this machine's desktop ("cops watch"); the session keeps running on host "${host}". Brings it to the front if it is already open.`,
    mirrorStateOpen: "OPEN on the desktop: clicking brings the existing window to the front",
    mirrorStateClosed: "NOT open on the desktop: clicking opens a new window",
    openingMirror: "opening…",
    mirrorOpened: (label) => `opened on the desktop: ${label}`,
    mirrorAlreadyOpen: (label, focused) =>
      focused ? `${label}: already open, brought to the front` : `${label}: already open (could not raise it, check your desktops)`,
    diagAskCliLabel: "CLI",
    diagAskQuestionLabel: "extra question (optional)",
    diagAskQuestionPlaceholder: "leave empty for a general diagnosis",
    diagAskBtn: "ask with this CLI",
    diagAsking: "opening… (~10-20s)",
    diagAskStarted: (name) => `✓ opened: ${name} — the live answer will appear in the terminal`,
    ioFieldMeta: {
      model: { label: "model", placeholder: "deepseek-v4-flash" },
      endpoint: { label: "endpoint (optional)", placeholder: "empty = local Ollama" },
      api_key: { label: "API key (optional, never stored)" },
      api_key_env: { label: "API key env name (optional)", placeholder: "UCLI_API_KEY" },
    },
    diagUcliHint: "Ask the ucli (unified-cli) rust agent directly — no fleet session, no tmux/Terminal, the answer appears right here. TOBEDECIDED#44(b).",
    diagUcliCwdLabel: "project directory",
    diagUcliCwdPlaceholder: "e.g. /home/fatihyuce/work/projects/...",
    diagUcliNewSession: "— new —",
    diagUcliNewSessionNameLabel: "new session name",
    diagUcliPromptLabel: "prompt",
    diagUcliPromptPlaceholder: "what do you want to ask ucli?",
    diagUcliModelLabel: "model",
    diagUcliEndpointLabel: "endpoint (optional)",
    diagUcliEndpointPlaceholder: "leave empty for local Ollama (http://localhost:11434/v1)",
    diagUcliApiKeyLabel: "API key (optional, never stored)",
    diagUcliSessionLabel: "session name (optional)",
    diagUcliSessionPlaceholder: "if set, remembers turns across calls (.ucli/chat/NAME.jsonl)",
    diagUcliBtn: "ask ucli",
    diagUcliAsking: "asking…",
    diagUcliResult: (answer, rounds, calls) => `${answer}\n\n(${rounds} model round${rounds === 1 ? "" : "s"}, ${calls} tool call${calls === 1 ? "" : "s"})`,
    diagLogTitle: "recent diag-log entries",
    diagLogLoading: "loading…",
    diagRunAfterFail: "Switch to the Diagnostics tab and run the spawn health test?",
    handoverMsgTitle: "handover text",
    handoverMsgHint: "the wrap-up message the handover button sends, in the currently selected language — copy it and paste it by hand without opening a separate CLI",
    protectedBadge: "caution",
    protectedHint: "keeps the guard alive — be careful with bulk selection/actions on this row",
    hostBadgeHint: (host) => `running on host "${host}" (not local)`,
    modelLiveDiffersHint: (registered) =>
      `The session is running on this model right now (switched live, or launched one-off). Registered/launch model: ${registered}`,
    hostsUnreachableMsg: (names) => `⚠ ${names.length} host(s) unreachable: ${names.join(", ")}`,
    hostsTitle: "Remote hosts",
    hostsDesc:
      "Connect another machine's claudeops panel here — that machine's sessions get added to the lists above with a host badge.",
    hostNameLabel: "name",
    hostBaseUrlLabel: "tunnel URL",
    hostTokenLabel: "token",
    hostExtraUrlsLabel: "backup URLs (optional)",
    hostExtraUrlsHint:
      "comma/newline-separated — tried in order if the one above fails, a working one gets promoted automatically",
    hostAddBtn: "add host",
    hostAdding: "adding…",
    hostSaveBtn: "save",
    hostSaving: "saving…",
    hostEditBtn: "edit",
    hostCancelEdit: "cancel",
    hostTokenKeepHint: "leave blank to keep the current token",
    hostRemoveBtn: "remove",
    hostRemoveConfirm: (name) =>
      `Remove host "${name}"? (sessions on that host aren't affected, only this panel's connection to it)`,
    hostTestBtn: "test now",
    hostTesting: "testing…",
    hostNone: "no remote hosts registered",
    cliInstallLabel: "CLI install",
    cliInstallDesc:
      "if any of these aren't already on this machine, installs into claudeops's own bin dir (~/.claude/claudeops/bin — claude/codex/copilot via npm --prefix, agy via the official antigravity.google install script's --dir flag — none of these are a real global/system install, just this user).",
    cliInstallBtn: "install",
    cliInstalling: "installing…",
    cliUpdateBtn: "update",
    cliManagedByUs: "installed by claudeops",
    cliFoundElsewhere: "already present on this system (left alone)",
    cliManualOnly: "no automated install, manually:",
    cliInstallHostLabel: "machine",
    cliInstallHostUnreachable: "can't reach this host right now",
    cliInstallHostOutdated: "this host's claudeops doesn't support this feature yet — needs a git pull + service restart there",
    hostConnected: "connected",
    hostUnreachable: "unreachable",
    hostLocalLabel: "this machine (local)",
    tunnelInfoLabel: "this machine's tunnel",
    tunnelNoneMsg: "no active tunnel (start with py/cops service install or web --tunnel)",
    settingsDesc: "These settings are stored server-side (~/.claude/claudeops/settings.json) — the same on every device/browser you sign in from, phone included. Each choice saves instantly.",
    settingsSingleUserWarning: "⚠ This is a single-user tool: never share your token or tunnel URL — anyone with access can drive your CLI sessions (and whichever provider account is behind them), which most providers' terms of service may not allow.",
    settingsAuto: "(auto)",
    settingsAutoModel: (model) => `(auto: ${model})`,
    themeLabel: "theme",
    themeSystem: "system",
    themeLight: "light",
    themeDark: "dark",
    handoverEffortLabel: "handover default effort",
    handoverEffortHint: "the effort level sessions reopened by handover (Phase 1/Phase 2/the panel's single-session handover button) get — becomes the respawned session's persistent default for its whole life until the NEXT handover",
    historyWarnLabel: "line warn threshold",
    historyWarnHint: "once terminal scrollback reaches this many lines, the Terminal view's counter is highlighted and the 'select needs attention' bulk button also picks up this session — flags it as approaching tmux's fixed 2000-line cap (past which the oldest lines get dropped)",
    layoutGridLabel: "layout density",
    layoutGridHint: "how many windows the Layout tab opens per desktop: 2 (side-by-side halves), 4 (2×2, default), 8 (4×2, dense)",
    fleetSortLabel: "fleet sort",
    fleetSortHint: "primary sort key for groups in the Running/Registered/Disabled/Retired tables — by name (default, the short name shown on screen) or by folder path (the project's full cwd — keeps sessions in the same folder next to each other, but the name doesn't always track the folder)",
    fleetSortByName: "by name",
    fleetSortByCwd: "by folder path",
    snapshotLabel: "Fleet snapshot",
    snapshotDesc: "save the running sessions, then (e.g. after a reboot) reopen all of them with the EXACT model/effort/permission-mode they were running with (open mirror windows are saved and reopened too)",
    snapshotNone: "no snapshot saved yet",
    snapshotInfo: (count, when, kind) =>
      `Last snapshot (${kind === "closing" ? "closing" : "manual"}): ${when}, ${count} session(s)`,
    snapshotSaveBtn: "Save snapshot",
    snapshotSaving: "Saving…",
    snapshotResumeBtn: "Resume latest snapshot",
    snapshotResuming: "Resuming…",
    snapshotHiddenLabel: "Start hidden (no window)",
    snapshotResultSummary: (started, alreadyRunning, failed) =>
      `${started} started, ${alreadyRunning} already running, ${failed} failed`,
    snapshotMirrorsSuffix: (mirrors) => (mirrors > 0 ? `, ${mirrors} mirror window(s)` : ""),
    snapshotMirrorResult: (opened, alreadyOpen, failed, skipped) =>
      `mirror windows: ${opened} opened, ${alreadyOpen} already open, ${failed} failed` +
      (skipped > 0 ? `, ${skipped} skipped (hidden start)` : ""),
    snapshotKindManual: "manual",
    snapshotKindClosing: "closing",
    snapshotHistoryLabel: "History",
    snapshotHistoryEmpty: "no other snapshots in history",
    snapshotHistoryRow: (count, when) => `${when} — ${count} session(s)`,
    snapshotHistoryResumeBtn: "Resume",
    defaultModelLabel: "default model for new/resume (per CLI)",
    providerBinLabel: "CLI binary path override (optional)",
    providerBinDesc:
      "If a CLI isn't found on the normal PATH (e.g. a project-local install), enter its full path here — leave blank to use normal PATH lookup. This is machine-local, it never touches a shared PATH location.",
    providerBinPlaceholder: "/full/path/to/binary",
    byokLabel: "API keys (BYOK)",
    byokDesc:
      "Key passed into the provider's own bring-your-own-key mechanism. Stored on this machine only, chmod 600; once saved it's never shown again, only whether it's set.",
    byokSetPlaceholder: "•••• (set, type to replace)",
    byokEmptyPlaceholder: "not set yet",
    byokClearBtn: "clear",
    ucliLimitsLabel: "ucli effort limits (max-steps / max-context-kib / max-tool-calls / max-output-tokens)",
    ucliLimitsDesc:
      "Override on top of ucli's medium/high effort preset numbers. Empty = the preset's own default. max-context-kib's unit is KiB, not tokens. max-output-tokens is the per-response output length cap — too low and a long task (e.g. a deep review) can burn its whole step budget on 'cut off, continue' rounds without ever finishing.",
    ucliLimitsMaxStepsLabel: "max-steps",
    ucliLimitsMaxContextKibLabel: "max-context-kib (KiB)",
    ucliLimitsMaxToolCallsLabel: "max-tool-calls",
    ucliLimitsMaxOutputTokensLabel: "max-output-tokens",
    ucliLimitsPlaceholderAuto: "empty = preset default",
    ucliLimitsReasoningLabel: "reasoning (--effort)",
    ucliLimitsReasoningHint:
      "The level passed to ucli as --effort (how much the model thinks). Auto: the session's effort (medium/high) goes through under the same name. Off: the flag is never passed (the old behaviour). If the model does not accept the field (read from Evren's capabilities, e.g. gemma-4-31b) it is not passed whatever you pick. Applies only to newly opened sessions.",
    ucliLimitsReasoningAuto: "auto (the session's effort)",
    ucliLimitsReasoningOff: "off (no flag)",
    ucliLimitsStreamLabel: "response streaming (--stream)",
    ucliLimitsStreamHint:
      "On by default. When on, the model response is requested as a stream: the 'thinking' / 'writing' phases and the amount received show in ucli's status file and in the row badge (which warns when the stream freezes), and the text is printed to the terminal live. The cost: (1) the answer appears twice in the terminal (the live stream, then the final output); (2) if the stream breaks off mid-way (a network drop) the call is NOT retried and the task fails, whereas a non-streamed call that drops before any answer arrives is retried. Applies only to newly opened sessions.",
    ucliLimitsStreamOff: "off",
    ucliLimitsStreamOn: "on (default)",
    ucliUsageWarnLabel: "ucli usage warning (quota-equivalent tokens per session)",
    ucliUsageWarnDesc:
      "The token badge turns amber/red at these thresholds. The number is what hits the Evren account quota (cached input counts 3%), not the raw total; it is the per-session sum since the process started. Colour only: nothing is stopped. Empty = default, off or 0 = that level disabled.",
    ucliUsageWarnAmberLabel: "amber threshold",
    ucliUsageWarnRedLabel: "red threshold",
    ucliUsageWarnPlaceholder: (def) => `empty = ${def}`,
    tunnelWatchLabel: "tunnel health watch",
    tunnelWatchHint:
      "If the public tunnel address answers HTTP 530 three checks in a row (about 3 minutes: the tunnel dropped from Cloudflare but the service still looks 'active'), cloudflared is restarted: the address CHANGES and an ntfy notice goes out. When off, a dropped tunnel needs a manual restart. A change applies within a minute, without restarting the tunnel. Works for the quick tunnel only (not a named tunnel).",
    tunnelWatchOn: "on (recommended)",
    tunnelWatchOff: "off",
    defaultEffortLabel: "default effort for new sessions (per CLI)",
    routingGuidanceLabel: "model/effort routing guidance",
    routingGuidanceDesc:
      "Newly opened sessions get a 'start low, pick sub-agent/model per task' guidance (claude: appended to the system prompt on every launch; codex: a marked block in ~/.codex/AGENTS.md, agy: in ~/.gemini/GEMINI.md). Running sessions are unaffected until reopened. Leave the text empty to use the bundled default. The global file path for copilot is not verified yet (account quota exhausted).",
    routingGuidancePlaceholder: "empty = bundled default text (data/routing.md)",
    ucliWebLabel: "ucli web tools (search / page fetch)",
    ucliWebDesc:
      "Applies only to ucli sessions newly opened from claudeops; running ones keep their old settings, and the panel does not need a restart. Search is ON by default: with an empty address the local SearXNG managed by claudeops is used (a docker container reachable from this machine only; this temporary bridge goes away once ucli does search itself). Page fetch (fetch_url) is OFF by default and opens only to the domains listed below.",
    ucliWebSearchUrlLabel: "search address (SearXNG)",
    ucliWebSearchUrlPlaceholder: "empty = automatic local SearXNG",
    ucliWebSearchUrlHint:
      "SearXNG address, e.g. http://127.0.0.1:8888/search. When set it wins and docker is left alone. An invalid address leaves search OFF; it never redirects elsewhere.",
    ucliWebDockerLabel: "automatic local search (docker)",
    ucliWebDockerHint:
      "While the search address is empty, the SearXNG container managed by claudeops is set up or started when a ucli session opens. Not used when a search address is set.",
    ucliWebDockerAuto: "on (default)",
    ucliWebDockerOff: "off",
    ucliWebFetchLabel: "domains allowed for page fetch",
    ucliWebFetchPlaceholder: "empty = fetch_url off, e.g. en.wikipedia.org, docs.rs",
    ucliWebFetchHint:
      "Exact domain names separated by commas or spaces (no wildcards). ucli only allows HTTP(S) GET requests to these.",
    ucliWebStateUrl: (url) => `Search: ${url}`,
    ucliWebStateUrlInvalid: "Search: invalid address, stays OFF (must start with http:// or https://)",
    ucliWebStateAuto: "Search: automatic local SearXNG (docker)",
    ucliWebStateOff: "Search: off",
    ucliWebFetchOn: "Page fetch: open to the listed domains",
    ucliWebFetchOff: "Page fetch: off",
    ucliScriptLabel: "ucli script layer (Lua)",
    ucliScriptDesc:
      "The model writes one short Lua program; ucli runs it inside its own process and calls its tools from that program, and only the small value the program returns goes back to the model. Applies only to ucli sessions newly opened from claudeops; running ones keep their old settings. OFF by default: the token saving has not been shown by a controlled measurement yet, the proven value is accuracy on mechanical work (e.g. counting letters). Every tool call made inside a script counts separately against the max-tool-calls budget above.",
    ucliScriptModeLabel: "script mode (--allow-script)",
    ucliScriptModeHint:
      "Read-only: scripts may only call read-only tools. Full: scripts may call EVERYTHING the session already gives the model (writes only if the session was opened with write permission; also fetch_url, web_search and MCP tools). The gates are the model's own, a script gains no extra authority. If the installed ucli binary does not know the flag it is silently skipped (logged in the diagnostics log).",
    ucliScriptOff: "off (default)",
    ucliScriptRead: "read-only (read)",
    ucliScriptFull: "full",
    tabHintToggle: "Show/hide description",
    tabSettingsGeneral: "general",
    tabSettingsModels: "models",
    tabSettingsFleet: "fleet",
    tabSettingsLayout: "layout",
    tabSettingsUsage: "usage",
    tabDiagStatus: "status",
    tabDiagAsk: "ask",
    tabDiagLog: "log",
    usageWarning:
      "⚠ Checking actually sends `/usage` to a RUNNING session of that CLI, briefly changing its screen (one nobody's watching is preferred) — not automatic/continuous, only when you press it.",
    usageCheckBtn: "Check usage",
    usageChecking: "checking…",
    usageNotSupported: "not supported",
    usageNoSession: "no running session",
    usageAllBusy: "all running sessions are busy or awaiting a password, could not check right now",
    usageSendFailed: "could not send command",
    usageParseFailed: "could not read the response",
    usageCheckedVia: (name) => `via ${name}`,
    contextBtn: "Check context",
    contextChecking: "checking…",
    contextHint: "injects /context into this session to show its context-window usage (won't run if the session is busy or awaiting a password)",
    contextUnsupported: "not supported for this CLI",
    contextNoTmux: "this session isn't tmux-backed",
    contextBusy: "session is busy right now, could not check",
    contextMasked: "session is awaiting masked input (e.g. a password), could not check",
    contextSendFailed: "could not send command",
    contextParseFailed: "could not read the response",
    pagePrev: "prev",
    pageNext: "next",
    pageOf: (page, total) => `page ${page}/${total}`,
    groupRunningBadge: "something in this group is running",
    collapseAllBtn: "collapse all",
    expandAllBtn: "expand all",
    searchPlaceholder: "search name or cwd…",
    searchClear: "clear search",
    noSearchMatches: "Nothing matches the search.",
    tabTeam: "Team",
    tabSteward: "Steward",
    stewardDesc: "The steward is the scheduler that tours your projects: answer its open questions here (or from the /q link on your phone) and the answer reaches the session on the next tick. Projects and the idea inbox are the same data as py/cops steward.",
    stewardOff: "Loop is off (steward.enabled) — records are visible, nothing ticks on its own; the \"tick\" button still works.",
    stewardMode: (mode) => (mode === "observe" ? "mode: observe (actions touching sessions are only recorded)" : `mode: ${mode}`),
    stewardLastTick: (ago) => `last tick ${ago}`,
    stewardNoTick: "no tick yet",
    stewardBrain: "brain",
    stewardTickBtn: "tick",
    stewardStatQuestions: "open questions",
    stewardStatIdeas: "new ideas",
    stewardStatPending: "pending items",
    stewardStatProjects: "projects",
    stewardQuestionsTitle: "Questions",
    stewardNoQuestions: "No open questions.",
    stewardAnswerPlaceholder: "answer… (an option number works too)",
    stewardAnswerBtn: "Answer",
    stewardAnswered: "answered",
    stewardAskTitle: "Ask a question (a note to yourself/the brain; also pushed to your phone)",
    stewardAskPlaceholder: "question text",
    stewardAskOptionsPlaceholder: "options, comma-separated (optional): yes, no, later",
    stewardAskBtn: "Ask",
    stewardProjectsTitle: "Projects",
    stewardNoProjects: "No steward projects yet — py/cops steward import takes the roster.",
    stewardColProject: "project",
    stewardColPhase: "phase",
    stewardColPriority: "priority",
    stewardColNext: "next step (card)",
    stewardColVisit: "last visit",
    stewardNever: "never",
    stewardIdeasTitle: "Idea inbox",
    stewardNoIdeas: "No new ideas.",
    stewardIdeaPlaceholder: "idea…",
    stewardIdeaAddBtn: "Add",
    stewardIdeaLater: "later",
    stewardIdeaDrop: "drop",
    stewardRecentTitle: "Recent actions",
    stewardDry: "dry",
    orchDesc: "Send the same task to several sessions and compare the answers. An optional controller can write its own brief for the task first; an optional decider can see the workers' answers and make the final call — with neither assigned, the result is decided by majority vote among the workers. The controller (if any) gets a result message once the run finishes.",
    orchLineupTitle: "Lineup",
    orchAddSelectedBtn: "Add selected",
    orchAddSelectedHint: "Adds the sessions checked in the Running tab (running + local + holding a conversation) to the lineup as workers",
    orchNoSelectionMsg: "Check at least one session in the Running tab first.",
    orchSkippedIneligible: (names) => `skipped (not eligible): ${names}`,
    orchLineupEmpty: "Lineup is empty — check sessions in the Running tab and click \"Add selected\".",
    orchRemoveBtn: "remove",
    orchRoleLabel: (role) => {
      const m: Record<string, string> = { worker: "worker", controller: "controller", decider: "decider" };
      return m[role] ?? role;
    },
    orchNeedsWorkerMsg: "at least one participant with the \"worker\" role is required",
    orchBriefLabel: "Brief (written by the controller, sent to the workers)",
    orchHandoffLabel: "result message sent to the controller",
    orchTaskLabel: "Task",
    orchTaskPlaceholder: "What should the workers do/answer…",
    orchVerdictHintLabel: "verdict format hint (optional)",
    orchVerdictHintPlaceholder: "e.g. answer with only yes or no",
    orchTimeoutLabel: "worker timeout (s)",
    orchRunBtn: "Run as team",
    orchStarting: "starting…",
    orchRunConfirm: (names, task) => `These sessions will be messaged: ${names.join(", ")}\n\nTask: ${task}\n\nProceed?`,
    orchCancelRunBtn: "cancel run",
    orchCancelRunConfirm: "Cancel this run? (messages already sent can't be recalled, this only stops waiting)",
    orchBackBtn: "◀ back",
    orchStatusLabel: (status) => {
      const m: Record<string, string> = {
        briefing: "writing brief", working: "working", deciding: "deciding",
        done: "done", needs_human: "needs a human", failed: "failed", cancelled: "cancelled",
      };
      return m[status] ?? status;
    },
    orchResultStatusLabel: (status) => {
      const m: Record<string, string> = { ok: "ok", timeout: "timed out", cancelled: "cancelled", send_failed: "send failed", no_envelope: "no verdict format", unreachable: "unreachable", pending: "pending" };
      return m[status] ?? status;
    },
    orchOutcomeMethodLabel: (method) => {
      const m: Record<string, string> = { decider: "decider", unanimous: "unanimous", majority: "majority", single_worker: "single worker", no_consensus: "no consensus", none: "no result" };
      return m[method] ?? method;
    },
    orchFinalLabel: "Result",
    orchTallyLabel: "Votes",
    orchAbstainedLabel: "Abstained",
    orchHistoryTitle: "Run history",
    orchHistoryEmpty: "No runs yet.",
    orchShowMoreBtn: "show more",
    orchViewBtn: "view",
  },
};
