/**
 * Ayarlar > Araçlar: sohbet ayna yedeği (chat_mirror.sh) durumu + systemd user timer kur/çalıştır (`chat_backup.py`).
 * Kurulum başarısız olursa sunucu tek satırlık `manual_command` döndürür; burada kopyalanabilir gösterilir.
 */
import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../api/client";
import { describeApiError } from "../api/errors";
import { showToast } from "../state/toast";
import { useLang } from "../i18n/LangContext";

interface BackupStatus {
  ok: boolean;
  script_exists: boolean;
  dest: string;
  cleanup_period_days: number | null;
  timer_enabled: string;
  timer_active: string;
  installed: boolean;
  last_done: string;
  last_line: string;
  manual_command: string;
  error?: string;
}

export function ChatBackupSection() {
  const { t, lang } = useLang();
  const tr = lang === "tr";
  const [s, setS] = useState<BackupStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [manual, setManual] = useState("");

  async function load() {
    try {
      setS(await apiGet<BackupStatus>("/api/chat-backup"));
    } catch (e) {
      showToast(describeApiError(e, t));
    }
  }
  useEffect(() => {
    void load();
  }, []);

  async function act(action: "install" | "run") {
    setBusy(true);
    try {
      const res = await apiPost<{ ok: boolean; error?: string; manual_command?: string }>("/api/chat-backup", { action });
      if (!res.ok) {
        showToast(res.error || "error");
        if (res.manual_command) setManual(res.manual_command);
      } else {
        setManual("");
      }
    } catch (e) {
      showToast(describeApiError(e, t));
    } finally {
      setBusy(false);
      await load();
    }
  }

  return (
    <div className="opts" id="settingsChatBackupPanel">
      <span className="opts-hint" style={{ flexBasis: "100%" }}>
        <b>{tr ? "Sohbet yedeği" : "Chat backup"}</b>{" "}
        {tr
          ? "Claude/Codex/agy/ucli sohbetleri silinmeden günlük ayna yedeğe kopyalanır (rsync, silme yok). Günlük çalışma systemd user timer ile."
          : "Claude/Codex/agy/ucli chats are copied to a mirror daily without deleting anything (rsync). Runs via a systemd user timer."}
      </span>
      {s && (
        <>
          <span className="opts-hint" style={{ flexBasis: "100%" }}>
            {tr ? "Hedef" : "Target"}: <code>{s.dest}</code> · cleanupPeriodDays: <b>{s.cleanup_period_days ?? "—"}</b> ·{" "}
            {tr ? "timer" : "timer"}: <b>{s.installed ? `${s.timer_enabled}/${s.timer_active}` : tr ? "kurulu değil" : "not installed"}</b>
          </span>
          <span className="opts-hint" style={{ flexBasis: "100%" }}>
            {tr ? "Son yedek" : "Last backup"}: {s.last_done || (tr ? "kayıt yok" : "none yet")}
          </span>
          <div style={{ display: "flex", gap: ".5rem", flexBasis: "100%" }}>
            <button type="button" className="go" disabled={busy || !s.script_exists} onClick={() => void act("install")}>
              {s.installed ? (tr ? "Timer'ı yeniden kur" : "Reinstall timer") : tr ? "Kur" : "Install"}
            </button>
            <button type="button" disabled={busy || !s.script_exists} onClick={() => void act("run")}>
              {tr ? "Şimdi çalıştır" : "Run now"}
            </button>
          </div>
          {!s.script_exists && (
            <span className="opts-hint" style={{ color: "var(--red)" }}>
              {tr ? "chat_mirror.sh bulunamadı" : "chat_mirror.sh not found"}
            </span>
          )}
          {manual && (
            <span className="opts-hint" style={{ flexBasis: "100%" }}>
              {tr ? "Elle çalıştır" : "Run manually"}: <code style={{ userSelect: "all" }}>{manual}</code>
            </span>
          )}
        </>
      )}
    </div>
  );
}
