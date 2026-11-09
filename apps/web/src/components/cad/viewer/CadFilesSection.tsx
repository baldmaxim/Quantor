'use client';

import type { CadViewDiagnosticsRead } from '@quantor/api-client';
import type { FC } from 'react';

import { InspectorSection } from '@/components/ui';
import { cadArtifactUrl, shortSha } from '@/lib/cad/artifacts';
import { formatBytes } from '@/lib/format';

interface ICadFilesSectionProps {
  projectId: string;
  revisionId: string;
  jobId: string;
  diagnostics: CadViewDiagnosticsRead;
}

const LINK =
  'inline-flex min-h-[44px] min-w-0 flex-1 items-center text-accent underline underline-offset-4 [overflow-wrap:anywhere]';

/**
 * Файлы вида. Только ссылки на скачивание через API: содержимое артефактов (HTML, скрипты) на
 * странице не открывается и не встраивается, имена - относительные, без путей хранилища.
 */
export const CadFilesSection: FC<ICadFilesSectionProps> = ({
  projectId,
  revisionId,
  jobId,
  diagnostics,
}) => {
  const { dxf, files } = diagnostics;
  const others = files.filter((file) => file.name !== dxf?.name);

  return (
    <InspectorSection title="Файлы">
      <div className="flex min-w-0 flex-col gap-[var(--s-5)]">
        {dxf ? (
          <div className="flex flex-col gap-[var(--s-3)] rounded-[var(--radius-md)] border border-border-strong bg-surface-muted p-[var(--s-5)]">
            <a
              href={cadArtifactUrl(projectId, revisionId, jobId, dxf.name)}
              download
              className="ctl press inline-flex h-[var(--h-ctl)] items-center justify-center self-start rounded-[var(--radius-sm)] border border-accent bg-accent px-[var(--s-5)] text-sm font-medium text-accent-contrast hover:bg-accent-hover max-md:h-[44px] max-md:w-full"
            >
              Скачать DXF
            </a>
            <p className="text-xs text-muted [overflow-wrap:anywhere]">
              {dxf.name} · {formatBytes(dxf.size)}
            </p>
            <p className="mono text-xs [overflow-wrap:anywhere]" data-testid="cad-dxf-sha">
              SHA-256: {dxf.sha256}
            </p>
            <p className="text-xs text-muted">Кандидат движка: до приёмки инженером в работу не идёт.</p>
          </div>
        ) : (
          <p className="text-xs text-muted">DXF в этой попытке не создан.</p>
        )}

        {others.length > 0 && (
          <ul className="flex flex-col rounded-[var(--radius-md)] border border-border">
            {others.map((file) => (
              <li
                key={file.name}
                className="flex flex-wrap items-center gap-x-[var(--s-5)] gap-y-[var(--s-2)] border-b border-border px-[var(--s-5)] py-[var(--s-3)] text-xs last:border-b-0"
              >
                <a
                  href={cadArtifactUrl(projectId, revisionId, jobId, file.name)}
                  download
                  className={LINK}
                >
                  {file.name}
                </a>
                <span className="mono text-muted">{formatBytes(file.size)}</span>
                <span className="mono text-muted" title={file.sha256}>
                  {shortSha(file.sha256)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </InspectorSection>
  );
};
