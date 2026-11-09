'use client';

import type { CadJobRead } from '@quantor/api-client';
import type { FC } from 'react';

import { StatusBadge } from '@/components/ui';
import { cadArtifactUrl, shortSha } from '@/lib/cad/artifacts';
import { resultInfo } from '@/lib/cad/stages';
import { formatBytes } from '@/lib/format';

interface ICadResultProps {
  projectId: string;
  revisionId: string;
  job: CadJobRead;
  /** Номер выбранной попытки. */
  attempt: number;
}

/**
 * Результат выбранной попытки. Файлы задания принадлежат только `result_attempt`: у любой
 * другой попытки (в том числе у текущей, пока результата нет) выпущенных файлов нет.
 */
export const CadResult: FC<ICadResultProps> = ({ projectId, revisionId, job, attempt }) => {
  const own = job.result_attempt !== null && job.result_attempt === attempt;
  const info = own ? resultInfo(job.result_status) : null;

  return (
    <section className="flex flex-col gap-[var(--s-4)] rounded-[var(--radius-md)] border border-border-strong bg-surface p-[var(--s-6)]">
      <h2 className="text-sm font-medium">Результат</h2>

      {!own ? (
        <p className="text-xs text-muted">У этой попытки нет выпущенного результата.</p>
      ) : (
        <>
          {info && (
            <div className="flex flex-col items-start gap-[var(--s-3)]">
              <StatusBadge tone={info.tone} dot={false} wrap>
                {info.label}
              </StatusBadge>
              {info.hint && <p className="text-xs text-muted">{info.hint}</p>}
            </div>
          )}
          {job.artifacts.length === 0 ? (
            <p className="text-xs text-muted">Файлов нет.</p>
          ) : (
            <ul className="flex flex-col rounded-[var(--radius-md)] border border-border">
              {job.artifacts.map((artifact) => (
                <li
                  key={artifact.name}
                  className="flex flex-wrap items-center gap-x-[var(--s-5)] gap-y-[var(--s-2)] border-b border-border px-[var(--s-5)] py-[var(--s-3)] text-xs last:border-b-0"
                >
                  <a
                    href={cadArtifactUrl(projectId, revisionId, job.job_id, artifact.name)}
                    download
                    className="inline-flex min-h-[44px] min-w-0 flex-1 items-center text-accent underline underline-offset-4 [overflow-wrap:anywhere]"
                  >
                    {artifact.name}
                  </a>
                  <span className="mono text-muted">{formatBytes(artifact.size)}</span>
                  <span className="mono text-muted" title={artifact.sha256}>
                    {shortSha(artifact.sha256)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
};
