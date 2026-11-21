/** Değnekçi > İşler: gönderilen direktifler (son 20): teslim durumu + hedef projenin TODO.md satırı açık mı/kapandı mı/yok mu.
 *  Gerekçe (sahip 20 Kas): "gönder deyince TODO olmalı yoksa kaybolur". Salt okunur; 15 sn'de bir tazelenir. */
import { useCallback, useEffect, useState } from "react";
import { getStewardDirectives } from "../api/client";
import type { StewardDirectiveRow } from "../api/client";
import { describeApiError } from "../api/errors";
import { useLang } from "../i18n/LangContext";

export function StewardDirectives() {
  const { t } = useLang();
  const [rows, setRows] = useState<StewardDirectiveRow[]>([]);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await getStewardDirectives();
      if (r.ok) {
        setRows([...(r.deliveries ?? [])].reverse());
        setErr("");
      }
    } catch (e) {
      setErr(describeApiError(e, t));
    }
  }, [t]);

  useEffect(() => {
    void load();
    const h = window.setInterval(() => void load(), 15000);
    return () => window.clearInterval(h);
  }, [load]);

  const todoLabel = (s?: string) => (s === "open" ? t.stewardDirTodoOpen : s === "closed" ? t.stewardDirTodoClosed : t.stewardDirTodoMissing);

  return (
    <>
      <h3 style={{ margin: ".4rem 0 0" }}>{t.stewardDirTitle}</h3>
      {err && <span className="opts-hint">⚠ {err}</span>}
      {rows.length === 0 && !err && <span className="opts-hint">{t.stewardDirNone}</span>}
      {rows.map((d) => (
        <div key={d.id} className="legend" style={{ margin: 0 }}>
          <span className="cli-badge">{d.status}</span> <b>{d.name}</b> <span className="opts-hint">#{d.id}</span>
          {" · "}
          <span className="cli-badge" title={t.stewardDirTodoHint}>{todoLabel(d.todo_state)}</span>
          {d.at ? <span className="opts-hint"> · {new Date(d.at * 1000).toLocaleString()}</span> : null}
          {d.status === "failed" && (d.reason || d.error) ? <span className="opts-hint"> · ⚠ {d.reason || d.error}</span> : null}
        </div>
      ))}
    </>
  );
}
