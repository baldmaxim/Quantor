'use client';

import type { DocQuestionOut } from '@quantor/api-client';
import type { FC } from 'react';

import { DocQuestionRow } from './DocQuestionRow';

/**
 * Список вопросов к документации: на md+ обычная таблица, ниже md строки становятся блоками
 * (вопрос, ответ, действия друг под другом), шапка остаётся только для программ чтения.
 */

interface ITableProps {
  readonly projectId: string;
  readonly questions: readonly DocQuestionOut[];
}

const TH = 'px-[var(--s-4)] py-[var(--s-3)] font-semibold';

export const DocQuestionsTable: FC<ITableProps> = ({ projectId, questions }) => (
  <div className="rounded-[var(--radius-md)] border border-border-strong bg-surface">
    <table
      aria-label="Вопросы к документации"
      className="w-full border-collapse text-left md:table-fixed max-md:block"
    >
      <thead className="max-md:sr-only">
        <tr className="border-b border-border-strong bg-surface-muted text-micro font-semibold tracking-[0.06em] text-muted uppercase">
          <th scope="col" className={`${TH} md:w-[35%]`}>
            Вопрос
          </th>
          <th scope="col" className={`${TH} md:w-[45%]`}>
            Ответ
          </th>
          <th scope="col" className={`${TH} md:w-[20%]`}>
            Действие
          </th>
        </tr>
      </thead>
      {questions.map((question) => (
        <DocQuestionRow key={question.code} projectId={projectId} question={question} />
      ))}
    </table>
  </div>
);
