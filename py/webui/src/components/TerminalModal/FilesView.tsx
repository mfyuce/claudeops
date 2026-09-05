/**
 * "Dosyalar" sub-tab (2026-09-05, user: "...folderları browse ve dosya
 * indirme ve dosyaları terminalde listeleme ve indirme ... şimdilik en
 * buyuk eksikliğim bu") — a small folder browser scoped to this session's
 * allowed roots (`files.py`'s `roots_for_session()`: the project's own cwd,
 * plus a claude session's own transcript folder). No polling — unlike
 * TerminalView/ChatView this only fetches on mount and when the user
 * navigates (a directory listing has no reason to refresh itself every
 * couple of seconds), mirroring ChatView's mount-only-while-active
 * lifecycle in `TerminalModal.tsx`.
 *
 * Downloads are plain `<a href>` navigations to `filesDownloadUrl()`, not a
 * JS fetch+blob — the backend's `Content-Disposition: attachment` header
 * makes the browser handle the save UI itself.
 */
import { useEffect, useState } from "react";
import { filesDownloadUrl, getFilesList } from "../../api/client";
import type { FileEntry, FileRoot } from "../../api/types";
import { useLang } from "../../i18n/LangContext";
import { isViewable } from "./fileViewerKind";

interface FilesViewProps {
  name: string;
  onView: (path: string) => void;
}

type FilesState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ok"; roots: FileRoot[]; path: string; entries: FileEntry[] };

function joinPath(base: string, entryName: string): string {
  return base.endsWith("/") ? base + entryName : `${base}/${entryName}`;
}

function parentOf(path: string): string {
  const idx = path.replace(/\/+$/, "").lastIndexOf("/");
  return idx > 0 ? path.slice(0, idx) : "/";
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[i]}`;
}

const BOX_STYLE: React.CSSProperties = {
  width: "min(560px, 85vw)",
  maxHeight: "calc(92vh - 160px)",
  overflow: "auto",
  boxSizing: "border-box",
};

export function FilesView({ name, onView }: FilesViewProps) {
  const { t, lang } = useLang();
  const [currentPath, setCurrentPath] = useState<string | null>(null);
  const [state, setState] = useState<FilesState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    void (async () => {
      try {
        const d = await getFilesList(name, lang, currentPath ?? undefined);
        if (cancelled) return;
        if (!d.ok) {
          setState({ kind: "error", message: d.error });
          return;
        }
        setState({ kind: "ok", roots: d.roots, path: d.path, entries: d.entries });
        if (currentPath === null) setCurrentPath(d.path);
      } catch (e) {
        if (cancelled) return;
        setState({ kind: "error", message: e instanceof Error ? e.message : String(e) });
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, lang, currentPath]);

  if (state.kind === "loading") return null;
  if (state.kind === "error") {
    return (
      <div style={BOX_STYLE}>
        {t.filesLoadError}
        {state.message}
      </div>
    );
  }

  const { roots, path, entries } = state;
  const atRoot = roots.some((r) => r.path === path);

  return (
    <div style={BOX_STYLE}>
      {roots.length > 1 && (
        <div style={{ display: "flex", gap: ".4rem", alignItems: "center", marginBottom: ".4rem", flexWrap: "wrap" }}>
          <span style={{ fontSize: ".75rem", opacity: 0.7 }}>{t.filesRootLabel}</span>
          {roots.map((r) => (
            <button key={r.key} type="button" onClick={() => setCurrentPath(r.path)} disabled={r.path === path}>
              {r.key}
            </button>
          ))}
        </div>
      )}
      <div
        style={{
          fontFamily: "monospace",
          fontSize: ".75rem",
          opacity: 0.8,
          marginBottom: ".4rem",
          overflowWrap: "anywhere",
        }}
      >
        {path}
      </div>
      {!atRoot && (
        <button type="button" style={{ marginBottom: ".4rem" }} onClick={() => setCurrentPath(parentOf(path))}>
          {t.filesUp}
        </button>
      )}
      {entries.length === 0 ? (
        <div>{t.filesEmpty}</div>
      ) : (
        <div>
          {entries.map((e) => (
            <FileRow key={e.name} entry={e} onOpenDir={() => setCurrentPath(joinPath(path, e.name))}
                     downloadUrl={filesDownloadUrl(name, lang, joinPath(path, e.name))}
                     downloadLabel={t.filesDownload} viewLabel={t.filesView}
                     onView={isViewable(e.name) ? () => onView(joinPath(path, e.name)) : null} />
          ))}
        </div>
      )}
    </div>
  );
}

function FileRow({
  entry, onOpenDir, downloadUrl, downloadLabel, viewLabel, onView,
}: {
  entry: FileEntry;
  onOpenDir: () => void;
  downloadUrl: string;
  downloadLabel: string;
  viewLabel: string;
  onView: (() => void) | null;
}) {
  const rowStyle: React.CSSProperties = {
    display: "flex", alignItems: "center", gap: ".4rem",
    padding: ".25rem 0", borderBottom: "1px solid var(--border)", fontSize: ".85rem",
  };
  if (entry.is_dir) {
    return (
      <button type="button" onClick={onOpenDir} style={{ ...rowStyle, width: "100%", textAlign: "left", background: "none" }}>
        <span>📁</span>
        <span style={{ flex: 1, overflowWrap: "anywhere" }}>{entry.name}</span>
      </button>
    );
  }
  return (
    <div style={rowStyle}>
      <span>📄</span>
      <span style={{ flex: 1, overflowWrap: "anywhere" }}>{entry.name}</span>
      <span style={{ opacity: 0.6, whiteSpace: "nowrap" }}>{formatSize(entry.size)}</span>
      {onView && (
        <button type="button" title={viewLabel} style={{ whiteSpace: "nowrap" }} onClick={onView}>
          👁
        </button>
      )}
      <a href={downloadUrl} download={entry.name} style={{ whiteSpace: "nowrap" }}>
        {downloadLabel}
      </a>
    </div>
  );
}
