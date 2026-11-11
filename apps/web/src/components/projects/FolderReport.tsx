import type { IFolderPlan } from '@/lib/uploads/packageFolder';

/**
 * Итог разбора выбранной папки: что не будет загружено и почему.
 *
 * Неполный комплект не отправляется молча и не отбрасывается молча: пользователь видит,
 * какого файла не хватает.
 */

export type FolderReportData = Pick<IFolderPlan, 'warnings' | 'skipped'> & {
  /** Сколько строк попало в очередь из этой папки. */
  readonly added: number;
};

export const FolderReport = ({ report }: { report: FolderReportData | null }) => {
  if (!report) return null;
  const { warnings, skipped, added } = report;
  if (warnings.length === 0 && skipped === 0 && added > 0) return null;

  return (
    <div
      role="status"
      className="flex flex-col gap-[var(--s-3)] rounded-[var(--radius-md)] border border-border px-[var(--s-6)] py-[var(--s-5)] text-xs"
    >
      {added === 0 && warnings.length === 0 && (
        <p className="text-warning">В папке нет файлов для загрузки.</p>
      )}

      {warnings.map((warning) => (
        <div key={warning.stem} className="flex flex-col gap-[var(--s-2)]">
          <p className="text-warning wrap-anywhere">
            Не загружено: {warning.stem} — неполный комплект.
          </p>
          <p className="text-muted wrap-anywhere">Не хватает: {warning.missing.join(', ')}</p>
        </div>
      ))}

      {skipped > 0 && <p className="text-muted">Пропущено файлов: {skipped}</p>}
    </div>
  );
};
