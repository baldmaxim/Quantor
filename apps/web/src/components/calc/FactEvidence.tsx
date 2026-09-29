'use client';

import type { CalcEvidenceRead } from '@quantor/api-client';
import Link from 'next/link';

/**
 * Основание утверждения: где в документе прочитано значение или кто и почему ввёл его вручную.
 *
 * Ссылка ведёт в рабочую область на лист и блок распознавания — инженер сверяет значение
 * с чертежом, не выходя из расчёта.
 */

const KIND_TITLES: Record<CalcEvidenceRead['kind'], string> = {
  MANUAL_ENTRY: 'Ручной ввод',
  ASSUMPTION_BASIS: 'Допущение',
  DOCUMENT_FRAGMENT: 'Фрагмент документа',
  REGION_TABLE: 'Таблица документа',
  REGION_TEXT: 'Текст документа',
};

const place = (item: CalcEvidenceRead): string | null => {
  const parts: string[] = [];
  if (item.page_index !== null) parts.push(`лист ${item.page_index + 1}`);
  if (item.locator) parts.push(item.locator);
  const region = item.region_locator;
  if (region?.kind === 'TABLE') {
    const rows = region.rows.map((row) => row + 1).join(', ');
    parts.push(`таблица ${region.table_index + 1}, строки ${rows}`);
    if (region.column !== undefined && region.column !== null) {
      parts.push(`столбец ${region.column + 1}`);
    }
  }
  return parts.length ? parts.join(' · ') : null;
};

export const documentHref = (projectId: string, item: CalcEvidenceRead): string | null => {
  if (!item.document_revision_id) return null;
  const query = new URLSearchParams({ revision: item.document_revision_id });
  if (item.page_index !== null) query.set('page', String(item.page_index + 1));
  if (item.region_id) query.set('region', item.region_id);
  return `/projects/${projectId}/workspace?${query.toString()}`;
};

export const FactEvidence = ({
  projectId,
  evidence,
}: {
  projectId: string;
  evidence: readonly CalcEvidenceRead[];
}) => {
  if (!evidence.length) {
    return <p className="text-xs text-muted">Основание не записано.</p>;
  }
  return (
    <ul className="flex list-none flex-col gap-[var(--s-2)] text-xs">
      {evidence.map((item) => {
        const where = place(item);
        const href = documentHref(projectId, item);
        return (
          <li
            key={item.id}
            className="flex flex-col gap-[var(--s-1)] border-l-2 border-border pl-[var(--s-3)]"
          >
            <span className="font-medium">
              {KIND_TITLES[item.kind]}
              {where ? ` · ${where}` : ''}
            </span>
            {item.basis && <span className="wrap-anywhere">Основание: {item.basis}</span>}
            {item.alternatives.length > 0 && (
              <span className="text-muted wrap-anywhere">
                Альтернативы: {item.alternatives.join('; ')}
              </span>
            )}
            {item.excerpt && (
              <span className="font-mono text-muted wrap-anywhere">«{item.excerpt}»</span>
            )}
            {href && (
              <Link
                href={href}
                className="inline-flex min-h-[44px] items-center text-accent underline-offset-2 hover:underline md:min-h-0"
              >
                Открыть в документе
              </Link>
            )}
          </li>
        );
      })}
    </ul>
  );
};
