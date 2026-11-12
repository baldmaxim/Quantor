'use client';

import type { DocCandidateOut } from '@quantor/api-client';
import Link from 'next/link';
import type { FC } from 'react';

import { Button } from '@/components/ui';
import { candidatePlace, docPageHref, pageText } from '@/lib/consistency/doc-questions';

/** Кандидат поиска: значение, цитата, место в комплекте, принять или отклонить. Отклонённый — без кнопок. */

interface IItemProps {
  readonly projectId: string;
  readonly candidate: DocCandidateOut;
  readonly busy: boolean;
  readonly onAccept?: (candidateId: string) => void;
  readonly onReject?: (candidateId: string) => void;
}

export const DocCandidateItem: FC<IItemProps> = ({
  projectId,
  candidate,
  busy,
  onAccept,
  onReject,
}) => {
  const place = candidatePlace(candidate);
  return (
    <li
      data-testid="doc-candidate"
      className="flex flex-col gap-[var(--s-2)] rounded-[var(--radius-sm)] border border-border px-[var(--s-4)] py-[var(--s-3)]"
    >
      <span className="text-base font-medium [overflow-wrap:anywhere]">
        {candidate.value.display || candidate.value_text}
      </span>
      <blockquote className="border-l-2 border-border-strong pl-[var(--s-3)] text-sm text-muted [overflow-wrap:anywhere]">
        {candidate.quote}
      </blockquote>
      <p className="text-xs text-muted [overflow-wrap:anywhere]">
        {candidate.file_name}, {pageText(candidate.page_index, candidate.page_label)}
        {' · '}
        <Link
          href={docPageHref(projectId, candidate.revision_id, candidate.page_index)}
          className="text-accent underline"
        >
          Открыть лист
        </Link>
      </p>
      {place && <p className="text-xs text-muted">{place}</p>}
      <p className="tabular text-xs text-muted">
        Оценка: {candidate.score}; встречается: {candidate.occurrences}
      </p>
      {onAccept && onReject && (
        <div className="flex flex-wrap gap-[var(--s-3)]">
          <Button variant="primary" disabled={busy} onClick={() => onAccept(candidate.id)}>
            Принять
          </Button>
          <Button disabled={busy} onClick={() => onReject(candidate.id)}>
            Отклонить
          </Button>
        </div>
      )}
    </li>
  );
};
