'use client';

import type { VorObjectRead } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { TopBar } from '@/components/shell/TopBar';
import { Button, EmptyState, ErrorState, SkeletonRows } from '@/components/ui';
import { cadAccess } from '@/lib/cad/access';
import { useCadVorLinks, vorErrorText } from '@/lib/cad/vor-queries';
import { env } from '@/lib/env';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';
import { useFeatures, useMeta, useProject } from '@/lib/queries';
import { OBJECT_KIND_LABELS } from '@/lib/vor-fill/format';
import { useExportVorFill, useVorFill } from '@/lib/vor-fill/queries';

import { VorFillLinkDialog } from './VorFillLinkDialog';
import { VorFillObjects } from './VorFillObjects';
import { VorFillTable } from './VorFillTable';

/**
 * Заполнение ВОР Заказчика (ADR-0055, п. 7): сравнение количеств Заказчика и Quantor по связанным
 * позициям, список «нет в ВОР» и выгрузка копии формы с колонками Quantor. Количества Quantor -
 * от движка; цен нет. Закрыто флагом `cad.export`.
 */

interface IScreenProps {
  readonly projectId: string;
}

const MAIN = 'min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)]';
const HEADING = 'text-micro font-semibold tracking-[0.06em] text-muted uppercase';
const LINK_BUTTON =
  'inline-flex min-h-[44px] items-center rounded-[var(--r-2)] border border-border px-[var(--s-4)] text-xs text-accent [-webkit-tap-highlight-color:transparent] [touch-action:manipulation]';

export const VorFillScreen: FC<IScreenProps> = ({ projectId }) => {
  const meta = useMeta();
  const access = cadAccess(meta.isSuccess, useFeatures());
  const project = useProject(projectId);
  const fill = useVorFill(projectId, access === 'open');
  const links = useCadVorLinks(projectId, access === 'open');
  const exported = useExportVorFill(projectId);
  const [target, setTarget] = useState<VorObjectRead | null>(null);

  if (access === 'pending') {
    return (
      <main className={MAIN}>
        <SkeletonRows rows={6} />
      </main>
    );
  }
  if (access === 'hidden') {
    return (
      <main className={MAIN}>
        <EmptyState title="Страница не найдена" />
      </main>
    );
  }

  const data = fill.data;
  const linked =
    target === null
      ? []
      : (links.data ?? [])
          .filter((link) => link.group_key === target.group_key)
          .map((link) => link.item);

  return (
    <>
      <TopBar
        crumbs={[
          { label: 'Проекты', href: '/projects' },
          { label: project.data?.name ?? '…', href: `/projects/${projectId}` },
          { label: 'Заполнение ВОР' },
        ]}
      />
      <main className={`${MAIN} md:py-[var(--s-7)]`}>
        <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-[var(--s-5)]">
          <p className="max-w-[80ch] text-sm text-muted">
            Количества Quantor посчитаны движком по листам проекта и стоят рядом с количествами
            Заказчика: ни во что они не подставляются. Цен нет.
          </p>
          {fill.isPending && <SkeletonRows rows={6} />}
          {fill.isError && (
            <ErrorState
              title="Сравнение не загрузилось"
              code={extractCode(fill.error)}
              description={extractMessage(fill.error) ?? errorMessage(extractCode(fill.error))}
              onRetry={() => void fill.refetch()}
            />
          )}
          {data && (
            <>
              <section
                aria-label="Выгрузка"
                className="flex flex-wrap items-center gap-[var(--s-3)]"
              >
                <Button
                  variant="primary"
                  disabled={!data.has_vor || exported.isPending}
                  onClick={() => exported.mutate()}
                >
                  {exported.isPending ? 'Формирование…' : 'Выгрузить заполненный ВОР (xlsx)'}
                </Button>
                {exported.data && (
                  <a
                    className={LINK_BUTTON}
                    href={`${env.apiBaseUrl}${exported.data.download_url}`}
                    download
                  >
                    Скачать {exported.data.file_name}
                  </a>
                )}
                {!data.has_vor && (
                  <span className="text-xs text-muted">
                    ВОР Заказчика не загружен: загрузите его на вкладке «Конструкции» рабочей
                    области CAD.
                  </span>
                )}
                {exported.isError && (
                  <span role="alert" className="text-xs text-danger">
                    {vorErrorText(exported.error)}
                  </span>
                )}
              </section>

              {data.warnings.length > 0 && (
                <ul
                  role="note"
                  className="m-0 flex list-none flex-col gap-[var(--s-1)] p-0 text-xs text-warning"
                >
                  {data.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              )}
              {data.unavailable.length > 0 && (
                <ul className="m-0 flex list-none flex-col gap-[var(--s-1)] p-0 text-xs text-muted">
                  {data.unavailable.map((entry) => (
                    <li key={entry.kind}>
                      {OBJECT_KIND_LABELS[entry.kind]}: {entry.reason}
                    </li>
                  ))}
                </ul>
              )}

              <section aria-label="Позиции ВОР" className="flex flex-col gap-[var(--s-3)]">
                <h2 className={HEADING}>Позиции ВОР</h2>
                <VorFillTable items={data.items} />
              </section>

              <section aria-label="Нет в ВОР" className="flex flex-col gap-[var(--s-3)]">
                <h2 className={HEADING}>Нет в ВОР Заказчика</h2>
                <VorFillObjects
                  objects={data.unlinked}
                  canLink={data.has_vor}
                  emptyText="Все объекты Quantor связаны с позициями ВОР."
                  onLink={setTarget}
                />
              </section>

              <details className="flex flex-col gap-[var(--s-3)]">
                <summary className="min-h-[44px] cursor-pointer text-xs text-muted">
                  Все объекты Quantor ({data.objects.length})
                </summary>
                <VorFillObjects
                  objects={data.objects}
                  canLink={data.has_vor}
                  emptyText="Объектов нет."
                  onLink={setTarget}
                />
              </details>

              {data.skipped_sheets.length > 0 && (
                <details>
                  <summary className="min-h-[44px] cursor-pointer text-xs text-muted">
                    Пропущено листов: {data.skipped_sheets.length}
                  </summary>
                  <ul className="m-0 list-none p-0 text-xs text-muted">
                    {data.skipped_sheets.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          )}
        </div>
      </main>
      {target !== null && data?.document_id && (
        <VorFillLinkDialog
          key={target.group_key}
          projectId={projectId}
          documentId={data.document_id}
          groupKey={target.group_key}
          title={target.title}
          linked={linked}
          onClose={() => setTarget(null)}
        />
      )}
    </>
  );
};
