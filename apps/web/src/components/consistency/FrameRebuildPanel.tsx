'use client';

import type { FrameOut } from '@quantor/api-client';
import Link from 'next/link';
import type { FC } from 'react';

import { Button } from '@/components/ui';
import { useRebuildFrame } from '@/lib/consistency/building-frame-queries';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

/** Вход сборки: подтверждённые планы, непроверенные планы и кнопка пересборки с итогом. */

interface IPanelProps {
  readonly projectId: string;
  readonly frame: FrameOut;
}

export const FrameRebuildPanel: FC<IPanelProps> = ({ projectId, frame }) => {
  const rebuild = useRebuildFrame(projectId);
  const result = rebuild.data;

  return (
    <section
      aria-label="Сборка каркаса"
      className="flex flex-col gap-[var(--s-3)] rounded-[var(--radius-md)] border border-border bg-surface px-[var(--s-5)] py-[var(--s-4)]"
    >
      <div className="flex flex-wrap items-center gap-[var(--s-4)]">
        <p className="tabular text-sm">
          Подтверждённых планов: <strong>{frame.confirmed_plans}</strong>
          {frame.candidate_plans > 0 && (
            <>
              {' · '}непроверенных: <strong>{frame.candidate_plans}</strong> — в каркас не идут,{' '}
              <Link className="text-accent underline" href={`/projects/${projectId}/sheets`}>
                подтвердить в листах комплекта
              </Link>
            </>
          )}
        </p>
        <Button
          variant="primary"
          className="ml-auto max-sm:ml-0"
          loading={rebuild.isPending}
          disabled={frame.confirmed_plans === 0}
          title={frame.confirmed_plans === 0 ? 'Нет подтверждённых планов' : undefined}
          onClick={() => rebuild.mutate()}
        >
          Собрать из паспортов
        </Button>
      </div>
      {result && (
        <p role="status" className="tabular text-sm text-muted">
          Создано: {result.created}, обновлено: {result.updated}, удалено: {result.removed},
          проверенные не тронуты: {result.kept_reviewed}.
        </p>
      )}
      {rebuild.isError && (
        <p role="alert" className="text-sm text-danger">
          {extractMessage(rebuild.error) ?? errorMessage(extractCode(rebuild.error))}
        </p>
      )}
    </section>
  );
};
