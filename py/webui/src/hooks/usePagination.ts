/**
 * Shared client-side pagination (TODO L74, 2026-09-02: list tabs 20 per page; TODO 1133, 22 Kas: page size
 * user-selectable + remembered). Pure/derived: `page` is the only bit of real state; `totalPages`/`pageItems`
 * are computed fresh from `items` every render, so a row disappearing never leaves a stale, too-high page.
 *
 * Page size: when the caller passes NO explicit `pageSize`, the size is the user's global choice
 * (localStorage `cops.pageSize`, default 20, one preference for every such list). An explicit `pageSize`
 * (small panels: 10) stays fixed and `sizeAdjustable` is false. `storageKey` (optional) also remembers the
 * page number of that list across reloads (`cops.page.<key>`); storage failures are ignored.
 */
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

export const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
const SIZE_KEY = "cops.pageSize";
const DEFAULT_SIZE = 20;
const listeners = new Set<() => void>();

function readSize(): number {
  try {
    const n = Number(localStorage.getItem(SIZE_KEY));
    return PAGE_SIZE_OPTIONS.includes(n) ? n : DEFAULT_SIZE;
  } catch {
    return DEFAULT_SIZE;
  }
}

function writeSize(n: number): void {
  try {
    localStorage.setItem(SIZE_KEY, String(n));
  } catch {
    /* storage blocked: the choice still applies for this page view via the listeners below */
  }
  memorySize = n;
  listeners.forEach((l) => l());
}

let memorySize: number | null = null;
const getSize = () => memorySize ?? readSize();
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

function readPage(key?: string): number {
  if (!key) return 1;
  try {
    const n = Number(localStorage.getItem(`cops.page.${key}`));
    return Number.isInteger(n) && n >= 1 ? n : 1;
  } catch {
    return 1;
  }
}

export interface UsePaginationResult<T> {
  page: number;
  setPage: (page: number) => void;
  totalPages: number;
  pageItems: T[];
  pageSize: number;
  totalItems: number;
  /** undefined when the size is fixed by the caller */
  setPageSize?: (size: number) => void;
}

export function usePagination<T>(items: T[], pageSize?: number, storageKey?: string): UsePaginationResult<T> {
  const globalSize = useSyncExternalStore(subscribe, getSize, () => DEFAULT_SIZE);
  const size = pageSize ?? globalSize;
  const [page, setPageState] = useState(() => readPage(storageKey));
  const totalPages = Math.max(1, Math.ceil(items.length / size));

  const setPage = useCallback(
    (p: number) => {
      setPageState(p);
      if (storageKey) {
        try {
          localStorage.setItem(`cops.page.${storageKey}`, String(p));
        } catch {
          /* ignore */
        }
      }
    },
    [storageKey],
  );

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages, setPage]);

  const clampedPage = Math.min(page, totalPages);
  const start = (clampedPage - 1) * size;
  const setPageSize = pageSize === undefined ? (n: number) => { writeSize(n); setPage(1); } : undefined;
  return {
    page: clampedPage, setPage, totalPages, pageItems: items.slice(start, start + size),
    pageSize: size, totalItems: items.length, setPageSize,
  };
}
