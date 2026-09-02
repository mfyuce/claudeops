/**
 * Shared prev/next pager for the 4 list tabs (TODO L74). Renders nothing
 * when everything fits on one page — no empty control clutter for the
 * common case (this fleet has historically stayed well under 20 rows per
 * tab, [[TOBEDECIDED#7]]).
 */
import { useLang } from "../../i18n/LangContext";

interface PaginationProps {
  page: number;
  totalPages: number;
  onChange: (page: number) => void;
}

export function Pagination({ page, totalPages, onChange }: PaginationProps) {
  const { t } = useLang();
  if (totalPages <= 1) return null;
  return (
    <div className="pagination">
      <button type="button" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        ‹ {t.pagePrev}
      </button>
      <span>{t.pageOf(page, totalPages)}</span>
      <button type="button" disabled={page >= totalPages} onClick={() => onChange(page + 1)}>
        {t.pageNext} ›
      </button>
    </div>
  );
}
