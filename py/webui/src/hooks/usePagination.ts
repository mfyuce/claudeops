/**
 * Shared client-side pagination (TODO L74, 2026-09-02 decision: all 4 list
 * tabs — Running/Registered/Disabled/Retired — 20 per page). Pure/derived:
 * `page` is the only bit of real state; `totalPages`/`pageItems` are
 * computed fresh from `items` every render, so a row disappearing (bulk
 * stop, adopt, etc.) never leaves a stale, too-high page number showing an
 * empty page — the effect below nudges `page` itself back down so a LATER
 * regrowth (e.g. the list filling back up) doesn't jump back to a page
 * number from before the shrink.
 */
import { useEffect, useState } from "react";

export interface UsePaginationResult<T> {
  page: number;
  setPage: (page: number) => void;
  totalPages: number;
  pageItems: T[];
}

export function usePagination<T>(items: T[], pageSize = 20): UsePaginationResult<T> {
  const [page, setPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const clampedPage = Math.min(page, totalPages);
  const start = (clampedPage - 1) * pageSize;
  return { page: clampedPage, setPage, totalPages, pageItems: items.slice(start, start + pageSize) };
}
