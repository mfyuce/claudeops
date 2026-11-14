/**
 * Uzak Masaüstü sekmesinde "Grafik oturum" bloğu: ekran kimde (yerel hesap mı, başka kullanıcı mı), kilit durumu ve
 * "Oturumumu öne al" düğmesi. Başka bir kullanıcı ekrandaysa adını gösteren satır içi onay ister. "Ekranı kilitle" / "Kilidi aç"
 * (14 Kas sahip kararı): yalnız kendi oturumumuz, onay penceresiyle; "Kilidi aç" `remote_desktop.unlock=off` ayarıyla gizlenir.
 * `session_auto_activate` ayarı açıksa (varsayılan kapalı) sekme açılınca bir kez onaysız öne alır (ayar önceden verilmiş onaydır).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { apiGraphicalStatus, apiSessionActivate, apiSessionLock } from "../api/client";
import { describeApiError } from "../api/errors";
import { showToast } from "../state/toast";
import type { GraphicalStatus } from "../api/types";
import { useLang } from "../i18n/LangContext";

export function GraphicalSession() {
  const { t } = useLang();
  const [st, setSt] = useState<GraphicalStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmUser, setConfirmUser] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const autoTried = useRef(false);

  const load = useCallback(async () => {
    try { setSt(await apiGraphicalStatus()); } catch { setSt(null); }
  }, []);

  const activate = useCallback(async (confirm: boolean) => {
    setBusy(true);
    setErr("");
    try {
      const r = await apiSessionActivate(confirm);
      if (r.need_confirm) setConfirmUser(r.active_user ?? "?");
      else {
        setConfirmUser(null);
        if (!r.ok) setErr(r.error ?? "?");
      }
    } catch (e) {
      setErr(String(e));
    }
    setBusy(false);
    void load();
  }, [load]);

  const setLock = useCallback(async (action: "lock" | "unlock") => {
    if (!window.confirm(action === "lock" ? t.gfxLockConfirm : t.gfxUnlockConfirm)) return;
    setBusy(true);
    setErr("");
    try {
      const r = await apiSessionLock(action, true);
      if (r.ok) showToast(action === "lock" ? t.gfxLockDone : t.gfxUnlockDone);
      else setErr(r.error ?? "?");
    } catch (e) {
      setErr(describeApiError(e, t));
    }
    setBusy(false);
    void load();
  }, [load, t]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!st || autoTried.current) return;
    autoTried.current = true;
    if (st.auto && st.ok && st.own && !st.own.active) void activate(true);
  }, [st, activate]);

  if (!st) return null;
  const mine = st.own?.active ?? false;
  let line = t.gfxNone;
  if (!st.ok) line = t.gfxNoSession;
  else if (mine) line = t.gfxYours;
  else if (st.other_active) line = t.gfxOther(st.active_user);

  return (
    <div className="opts-hint" style={{ margin: ".5rem 0", display: "flex", gap: ".5rem", flexWrap: "wrap", alignItems: "center" }}>
      <strong>{t.gfxTitle}:</strong>
      <span>{line}</span>
      {st.own?.locked === true && <span>{t.gfxLocked}</span>}
      {st.ok && st.own?.locked === false && (
        <button type="button" disabled={busy} onClick={() => void setLock("lock")}>{t.gfxLock}</button>
      )}
      {st.ok && st.own?.locked === true && st.unlock_enabled !== false && (
        <button type="button" className="stop" disabled={busy} onClick={() => void setLock("unlock")}>{t.gfxUnlock}</button>
      )}
      {st.ok && !mine && confirmUser === null && (
        <button type="button" className="start" disabled={busy} onClick={() => void activate(false)}>
          {busy ? t.gfxBringing : t.gfxBring}
        </button>
      )}
      {confirmUser !== null && (
        <>
          <span>{t.gfxConfirm(confirmUser)}</span>
          <button type="button" className="stop" disabled={busy} onClick={() => void activate(true)}>{t.gfxConfirmYes}</button>
          <button type="button" disabled={busy} onClick={() => setConfirmUser(null)}>{t.gfxCancel}</button>
        </>
      )}
      {err && <span>{t.gfxFailed(err)}</span>}
    </div>
  );
}
