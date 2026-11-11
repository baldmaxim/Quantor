'use client';

import Link from 'next/link';
import { useId, type FC } from 'react';

import type { IVorSource } from '@/lib/cad/vor-queries';

interface IVorSourcePickerProps {
  projectId: string;
  /** Книги .xlsx из документов проекта. */
  sources: readonly IVorSource[];
  loading: boolean;
  /** SHA-256 книги, которая сейчас стоит ВОРом: её документ показывается выбранным. */
  currentSha256: string | null;
  disabled: boolean;
  onPick: (revisionId: string) => void;
}

const SELECT =
  'h-[var(--h-ctl)] w-full min-w-0 rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:text-sm max-md:h-[44px]';

/**
 * Выбор ВОР Заказчика из документов проекта (вкладка «Документы»): книга .xlsx, последняя ревизия.
 * Выбор сразу запускает импорт: файл в CAD отдельно не загружается.
 */
export const VorSourcePicker: FC<IVorSourcePickerProps> = ({
  projectId,
  sources,
  loading,
  currentSha256,
  disabled,
  onPick,
}) => {
  const id = useId();

  if (sources.length === 0) {
    return loading ? (
      <p role="status" className="text-xs text-muted">
        Загрузка документов проекта…
      </p>
    ) : (
      <p className="text-xs text-muted">
        В документах проекта нет книг .xlsx — добавьте ВОР Заказчика на вкладке «Документы»{' '}
        <Link
          href={`/projects/${projectId}`}
          className="inline-flex min-h-[44px] items-center text-accent underline-offset-2 hover:underline md:min-h-0"
        >
          проекта
        </Link>
        .
      </p>
    );
  }

  const current = sources.find((source) => source.sha256 === currentSha256)?.revisionId ?? '';

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-2)]">
      <label htmlFor={id} className="text-xs text-muted">
        ВОР из документов проекта
      </label>
      <select
        id={id}
        value={current}
        disabled={disabled}
        className={SELECT}
        onChange={(event) => {
          if (event.target.value !== '') onPick(event.target.value);
        }}
      >
        <option value="" disabled>
          Выберите книгу .xlsx
        </option>
        {sources.map((source) => (
          <option key={source.revisionId} value={source.revisionId}>
            {source.fileName}
          </option>
        ))}
      </select>
    </div>
  );
};
