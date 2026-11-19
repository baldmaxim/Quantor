'use client';

import type { DocumentRead, DocumentRevisionRead } from '@quantor/api-client';
import type { FC } from 'react';

import { ButtonLink, Skeleton, StatusBadge, cx } from '@/components/ui';
import { IconBim, IconPdf, IconZip } from '@/components/ui/icons';
import { errorMessage } from '@/lib/errors';
import {
  countOf,
  documentKind,
  documentRecognitionStatus,
  formatBytes,
  geometryStatus,
} from '@/lib/format';
import { SHEETS_FORMS } from '@/lib/format';
import { documentOpenState, isViewable, latestOpenableRevision } from '@/lib/openability';

/**
 * Строка документа в карточке проекта.
 *
 * Показывает два независимых состояния: подготовку листов, от которой зависит просмотр, и
 * распознавание, от которого он не зависит. Действие «Открыть» стоит у каждого готового
 * документа — верхняя кнопка страницы одна, а документов в проекте бывает несколько.
 *
 * Строка выбирается: кнопка на имени растянута на строку псевдоэлементом, поэтому работают
 * клик по любому месту строки, Enter и Space. Выбранный документ показывается справа в панели
 * «Обработка». Кнопка «Открыть» - ссылка в рабочую область - лежит поверх растянутой кнопки и
 * клика по строке не вызывает.
 */

const ICONS: Record<string, typeof IconPdf> = {
  pdf: IconPdf,
  recognized_package: IconZip,
  revit: IconBim,
  navisworks: IconBim,
  ifc: IconBim,
};

export interface IDocumentRowProps {
  readonly projectId: string;
  readonly document: DocumentRead;
  /** `null`, пока ревизии не загружены. */
  readonly revisions: readonly DocumentRevisionRead[] | null;
  readonly total: number;
  /** Сколько распознанных пакетов того же имени скрыто в этой строке. */
  readonly packageCount?: number;
  readonly selected?: boolean;
  readonly onSelect?: (documentId: string) => void;
}

export const DocumentRow: FC<IDocumentRowProps> = ({
  projectId,
  document,
  revisions,
  total,
  packageCount = 0,
  selected = false,
  onSelect,
}) => {
  const Icon = ICONS[document.document_kind] ?? IconPdf;
  const latest = revisions?.at(-1) ?? null;
  const openable = revisions ? latestOpenableRevision(document, revisions) : null;
  const state = revisions ? documentOpenState(document, revisions) : null;

  const recognition = latest
    ? documentRecognitionStatus(document.document_kind, latest.processing_status)
    : null;
  const geometry = latest && isViewable(document) ? geometryStatus(latest.geometry_status) : null;
  const pageCount = latest?.source_metadata?.['page_count'];
  const sheets = latest && latest.sheet_count > 0 ? latest.sheet_count : pageCount;

  const href = openable ? `/projects/${projectId}/workspace?revision=${openable.id}` : null;
  // Готовые листы - норма: плашка только когда листы готовятся или не подготовились.
  const geometryNote = geometry && latest?.geometry_status !== 'ready' ? geometry : null;
  const meta = [
    documentKind(document.document_kind),
    latest ? formatBytes(latest.source_size) : null,
    typeof sheets === 'number' ? countOf(sheets, SHEETS_FORMS) : null,
    total > 1 ? `ревизий: ${total}` : null,
    packageCount > 0 ? `пакет распознавания${packageCount > 1 ? ` ×${packageCount}` : ''}` : null,
  ].filter((part): part is string => part !== null);

  return (
    <div
      className={cx(
        'relative grid grid-cols-[18px_minmax(0,1fr)_auto] items-start gap-x-[var(--s-4)] rounded-[var(--radius-sm)] px-[var(--s-3)] py-[var(--s-3)] transition-colors motion-reduce:transition-none',
        selected ? 'bg-accent-soft' : 'hover:bg-surface-muted',
      )}
    >
      <Icon className={cx('mt-[2px]', selected ? 'text-accent' : 'text-muted')} />

      <div className="min-w-0">
        <button
          type="button"
          aria-current={selected ? 'true' : undefined}
          title={document.display_name}
          onClick={() => onSelect?.(document.id)}
          className="block w-full cursor-pointer text-left text-sm leading-snug [-webkit-tap-highlight-color:transparent] [touch-action:manipulation] focus-visible:outline-none after:absolute after:inset-0 after:rounded-[var(--radius-sm)] after:content-[''] focus-visible:after:outline-2 focus-visible:after:-outline-offset-2 focus-visible:after:outline-[var(--focus)]"
        >
          <span className={cx('line-clamp-2 [overflow-wrap:anywhere]', selected && 'font-medium')}>
            {document.display_name}
          </span>
        </button>
        <p className="m-0 mt-[2px] text-xs text-muted">{meta.join(' · ')}</p>

        {(geometryNote || recognition || latest === null) && (
          <div className="mt-[var(--s-2)] flex flex-wrap items-center gap-[var(--s-3)]">
            {latest === null && <Skeleton className="h-[16px] w-[90px]" />}
            {geometryNote && (
              <StatusBadge tone={geometryNote.tone}>{geometryNote.label}</StatusBadge>
            )}
            {recognition && (
              // Над растянутой кнопкой строки: иначе подсказка не всплывает.
              <span title={recognition.hint ?? undefined} className="relative z-10">
                <StatusBadge tone={recognition.tone}>{recognition.label}</StatusBadge>
              </span>
            )}
          </div>
        )}

        {latest?.processing_error_code && (
          <p className="m-0 mt-[var(--s-2)] text-xs text-danger">
            {errorMessage(latest.processing_error_code)}
          </p>
        )}

        {state?.kind === 'geometry_failed' && (
          <p className="m-0 mt-[var(--s-2)] text-xs text-danger">
            Листы подготовить не удалось
            {state.errorCode ? `: ${errorMessage(state.errorCode)}` : '.'}
          </p>
        )}
      </div>

      {href && (
        <ButtonLink
          href={href}
          compact
          variant="ghost"
          aria-label={`Открыть ${document.display_name}`}
          className="relative z-10 flex-none"
        >
          Открыть
        </ButtonLink>
      )}
    </div>
  );
};
