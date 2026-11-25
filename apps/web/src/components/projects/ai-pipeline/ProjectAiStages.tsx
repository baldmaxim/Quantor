'use client';

import type { AiRunResult, ProjectAiPipelineRead } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { Button, ErrorState, Skeleton } from '@/components/ui';
import { cadErrorText } from '@/lib/cad/errors';

import { AiStageCard } from './AiStageCard';
import { AiStageSheetList } from './AiStageSheetList';
import { codexTargets, stageRows } from './aiPipelineView';
import { useProjectAiPipeline, useRunAiStage, useRunCodexReview } from './useProjectAiPipeline';

/**
 * Этапы проекта: прогон чертежей, проверка Claude, верификация, приёмка. Этапы считаются по всем
 * листам проекта. Запускаются только проверки (этапы 2 и 3); прогон чертежей ведут автопайплайн и
 * кнопки CAD.
 */

export interface IProjectAiStagesProps {
  readonly projectId: string;
}

type Engine = 'claude' | 'codex';

const SELECT =
  'h-[44px] min-w-0 rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:h-[var(--h-ctl)] md:text-sm';

const runText = (result: AiRunResult): string => {
  const skipped = result.skipped.length;
  const base = `Поставлено: ${result.queued}, пропущено: ${skipped}.`;
  return skipped > 0 ? `${base} Например: ${result.skipped[0]?.reason ?? ''}` : base;
};

export const ProjectAiStages: FC<IProjectAiStagesProps> = ({ projectId }) => {
  const query = useProjectAiPipeline(projectId, true);
  const run = useRunAiStage(projectId);
  const codex = useRunCodexReview(projectId);
  const [open, setOpen] = useState<number | null>(null);
  const [choice, setChoice] = useState<Engine>('claude');
  const [message, setMessage] = useState<string | null>(null);
  const data: ProjectAiPipelineRead | undefined = query.data;

  if (query.isPending) return <Skeleton className="mb-[var(--s-5)] h-[96px] w-full" />;
  if (query.isError || !data) {
    return (
      <div className="mb-[var(--s-5)]">
        <ErrorState
          title="Не удалось получить этапы проекта"
          onRetry={() => void query.refetch()}
        />
      </div>
    );
  }

  const engine: Engine = !data.available && data.codex_available ? 'codex' : choice;
  const busy = run.isPending || codex.isPending;
  const targets = codexTargets(data);
  const stage2 = data.stages.find((item) => item.stage === 2);
  const stage3 = data.stages.find((item) => item.stage === 3);

  const startReview = (): void => {
    setMessage(null);
    run.mutate('review', {
      onSuccess: (result) => setMessage(runText(result)),
      onError: (error) => setMessage(cadErrorText(error)),
    });
  };
  const startVerify = (): void => {
    setMessage(null);
    if (engine === 'claude') {
      run.mutate('verify', {
        onSuccess: (result) => setMessage(runText(result)),
        onError: (error) => setMessage(cadErrorText(error)),
      });
      return;
    }
    codex.mutate(
      targets.flatMap((row) => (row.walls_job_id ? [row.walls_job_id] : [])),
      {
        onSuccess: (result) =>
          setMessage(`Проверка Codex: поставлено ${result.queued}, отказов ${result.failed}.`),
        onError: (error) => setMessage(cadErrorText(error)),
      },
    );
  };

  const reviewDisabled = busy || !data.available || (stage2?.total ?? 0) === 0;
  const verifyDisabled =
    busy ||
    (engine === 'claude' ? !data.available || (stage3?.total ?? 0) === 0 : targets.length === 0);
  const expanded = data.stages.find((item) => item.stage === open) ?? null;

  return (
    <section
      aria-label="Этапы проекта"
      className="mb-[var(--s-5)] min-w-0 shrink-0 overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface"
    >
      <h2 className="m-0 border-b border-border px-[var(--s-6)] py-[var(--s-3)] text-sm font-medium">
        Этапы проекта
      </h2>
      <ol className="m-0 flex list-none flex-col p-0 md:flex-row">
        {data.stages.map((stage) => (
          <AiStageCard
            key={stage.stage}
            stage={stage}
            expanded={open === stage.stage}
            panelId="ai-stage-sheets"
            onToggle={() => setOpen(open === stage.stage ? null : stage.stage)}
            actions={
              stage.stage === 2 ? (
                <Button compact disabled={reviewDisabled} onClick={startReview}>
                  Запустить проверку Claude
                </Button>
              ) : stage.stage === 3 ? (
                <div className="flex flex-wrap items-center gap-[var(--s-3)]">
                  <select
                    aria-label="Чем верифицировать"
                    value={engine}
                    onChange={(event) =>
                      setChoice(event.target.value === 'codex' ? 'codex' : 'claude')
                    }
                    className={SELECT}
                  >
                    <option value="claude" disabled={!data.available}>
                      Claude
                    </option>
                    <option value="codex" disabled={!data.codex_available}>
                      {data.codex_available ? 'Codex' : 'Codex (недоступен)'}
                    </option>
                  </select>
                  <Button compact disabled={verifyDisabled} onClick={startVerify}>
                    Верифицировать
                  </Button>
                </div>
              ) : null
            }
          />
        ))}
      </ol>
      {message && (
        <p
          role="status"
          className="m-0 border-t border-border px-[var(--s-6)] py-[var(--s-3)] text-xs text-muted"
        >
          {message}
        </p>
      )}
      {expanded && (
        <div id="ai-stage-sheets" className="border-t border-border">
          <AiStageSheetList
            projectId={projectId}
            stageTitle={expanded.title}
            rows={stageRows(data, expanded.stage)}
          />
        </div>
      )}
    </section>
  );
};
