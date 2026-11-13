import { isMissingOnlyPdf, type IFolderPlan } from '@/lib/uploads/packageFolder';

/**
 * Итог разбора выбранной папки: что не будет загружено и почему.
 *
 * Неполный комплект не отправляется молча и не отбрасывается молча: пользователь видит,
 * какого файла не хватает.
 */

export type FolderReportData = Pick<IFolderPlan, 'warnings' | 'skipped'> & {
  /** Сколько строк попало в очередь из этой папки. */
  readonly added: number;
  /** Stem комплектов, чей пакет распознавания уже лежит в проекте. */
  readonly alreadyInProject: readonly string[];
  /** Stem комплектов без PDF: распознавание прикрепится к PDF, уже загруженному в проект. */
  readonly attachToExisting: readonly string[];
};

export const FolderReport = ({ report }: { report: FolderReportData | null }) => {
  if (!report) return null;
  const { warnings, skipped, added, alreadyInProject, attachToExisting } = report;
  if (
    warnings.length === 0 &&
    skipped === 0 &&
    added > 0 &&
    alreadyInProject.length === 0 &&
    attachToExisting.length === 0
  ) {
    return null;
  }

  return (
    <div
      role="status"
      className="flex flex-col gap-[var(--s-3)] rounded-[var(--radius-md)] border border-border px-[var(--s-6)] py-[var(--s-5)] text-xs"
    >
      {added === 0 && warnings.length === 0 && alreadyInProject.length === 0 && (
        <p className="text-warning">В папке нет файлов для загрузки.</p>
      )}

      {warnings.map((warning) =>
        isMissingOnlyPdf(warning) ? (
          <p key={warning.stem} className="text-warning wrap-anywhere">
            Не хватает PDF: {warning.stem}.pdf — добавьте его (перетащите или «выберите на диске»),
            комплект соберётся сам, или загрузите PDF отдельно, затем выберите папку снова.
          </p>
        ) : (
          <div key={warning.stem} className="flex flex-col gap-[var(--s-2)]">
            <p className="text-warning wrap-anywhere">
              Не загружено: {warning.stem} — неполный комплект.
            </p>
            <p className="text-muted wrap-anywhere">Не хватает: {warning.missing.join(', ')}</p>
          </div>
        ),
      )}

      {alreadyInProject.map((stem) => (
        <p key={stem} className="text-muted wrap-anywhere">
          Уже в проекте: {stem}
        </p>
      ))}

      {attachToExisting.map((stem) => (
        <p key={stem} className="text-muted wrap-anywhere">
          Распознавание прикрепится к загруженному PDF: {stem}.pdf
        </p>
      ))}

      {skipped > 0 && (
        <div className="flex flex-col gap-[var(--s-2)] text-muted">
          <p>Пропущено файлов: {skipped}</p>
          <p>Служебные файлы распознавалки (_source.json) не нужны.</p>
        </div>
      )}
    </div>
  );
};
