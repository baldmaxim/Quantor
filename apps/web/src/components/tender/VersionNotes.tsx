import type { TenderCalcVersionRead } from '@quantor/api-client';
import type { FC } from 'react';

import { EmptyState, StatusBadge } from '@/components/ui';

/** Вопросы расчёта (`questions.json`) и предупреждения портала при загрузке. */

interface INotesProps {
  readonly version: TenderCalcVersionRead;
}

const TITLE = 'text-micro font-semibold tracking-[0.06em] text-muted uppercase';
const ITEM =
  'rounded-[var(--radius-sm)] border border-border bg-surface px-[var(--s-5)] py-[var(--s-3)] text-sm [overflow-wrap:anywhere]';

export const VersionNotes: FC<INotesProps> = ({ version }) => (
  <>
    <section className="flex flex-col gap-[var(--s-4)]">
      <h3 className={TITLE}>Вопросы ({version.questions.length})</h3>
      {version.questions.length === 0 ? (
        <EmptyState compact title="Вопросов нет" />
      ) : (
        <ul className="m-0 flex list-none flex-col gap-[var(--s-3)] p-0">
          {version.questions.map((question, index) => (
            <li key={`${index}-${question.text}`} className={ITEM}>
              <p className="m-0">{question.text}</p>
              {(question.ref || question.ids.length > 0) && (
                <p className="m-0 mt-[var(--s-2)] text-xs text-muted">
                  {question.ref}
                  {question.ref && question.ids.length > 0 ? ' · ' : ''}
                  {question.ids.length > 0 && (
                    <span className="mono">{question.ids.join(', ')}</span>
                  )}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
    <section className="flex flex-col gap-[var(--s-4)]">
      <h3 className={TITLE}>Предупреждения ({version.warnings.length})</h3>
      {version.warnings.length === 0 ? (
        <EmptyState compact title="Предупреждений нет" />
      ) : (
        <ul className="m-0 flex list-none flex-col gap-[var(--s-3)] p-0">
          {version.warnings.map((warning, index) => (
            <li key={`${index}-${warning.code}`} className={ITEM}>
              <span className="flex flex-wrap items-center gap-[var(--s-3)]">
                <StatusBadge tone="warning">{warning.code}</StatusBadge>
                <span>{warning.message}</span>
              </span>
              {warning.view_key && (
                <p className="mono m-0 mt-[var(--s-2)] text-xs text-muted">{warning.view_key}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  </>
);
