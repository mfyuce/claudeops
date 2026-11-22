/**
 * Shared prev/next pager (TODO L74). Renders nothing when everything fits on one page and no page-size
 * choice applies. With `onPageSize` (TODO 1133) it also shows a page-size select; the select stays visible
 * while there are more rows than the smallest option, so a large choice can always be reduced again.
 */
import { useLang } from "../../i18n/LangContext";
import { PAGE_SIZE_OPTIONS } from "../../hooks/usePagination";

interface PaginationProps {
  page: number;
  totalPages: number;
  onChange: (page: number) => void;
  pageSize?: number;
  totalItems?: number;
  onPageSize?: (size: number) => void;
}

export function Pagination({ page, totalPages, onChange, pageSize, totalItems, onPageSize }: PaginationProps) {
  const { t } = useLang();
  const showSize = !!onPageSize && pageSize !== undefined && (totalItems ?? 0) > PAGE_SIZE_OPTIONS[0];
  if (totalPages <= 1 && !showSize) return null;
  return (
    <div className="pagination">
      {totalPages > 1 && (
        <>
          <button type="button" disabled={page <= 1} onClick={() => onChange(page - 1)}>
            ‹ {t.pagePrev}
          </button>
          <span>{t.pageOf(page, totalPages)}</span>
          <button type="button" disabled={page >= totalPages} onClick={() => onChange(page + 1)}>
            {t.pageNext} ›
          </button>
        </>
      )}
      {showSize && (
        <label>
          {t.pageSizeLabel}{" "}
          <select value={pageSize} onChange={(e) => onPageSize!(Number(e.target.value))}>
            {PAGE_SIZE_OPTIONS.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </label>
      )}
    </div>
  );
}
