'use client';

import type { FC } from 'react';

import type { CadFinishTemplateRead } from '@quantor/api-client';

import { Button, Skeleton } from '@/components/ui';
import { cadErrorText } from '@/lib/cad/errors';
import { buildFinishCsv, downloadCsv, finishCsvFilename } from '@/lib/cad/finish-csv';
import { useCadFinishSheet } from '@/lib/cad/finishes-queries';

import { CadFinishSheetTable } from './CadFinishSheetTable';
import { CadFinishTotals } from './CadFinishTotals';
import { CadFinishWarnings } from './CadFinishWarnings';

interface ICadFinishSheetProps {
  projectId: string;
  revisionId: string | null;
  pageIndex: number | null;
  load: boolean;
  templates: readonly CadFinishTemplateRead[];
  activeId: string | null;
  /** Выделить зону на листе, как выбор в списке зон. */
  onActivate: (id: string | null) => void;
}

/**
 * Ведомость отделки текущего листа (ADR-0042): зоны со слоями, предупреждения, итоги. Количества
 * считает сервер при чтении; это рабочая таблица пилота, не ВОР и не смета.
 */
export const CadFinishSheet: FC<ICadFinishSheetProps> = ({
  projectId,
  revisionId,
  pageIndex,
  load,
  templates,
  activeId,
  onActivate,
}) => {
  const sheet = useCadFinishSheet(projectId, revisionId, pageIndex, load);
  const data = sheet.data;

  return (
    <section
      aria-label="Ведомость отделки листа"
      className="flex min-w-0 flex-col gap-[var(--s-4)]"
    >
      <div className="flex flex-wrap items-center justify-between gap-[var(--s-2)]">
        <h4 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
          Ведомость листа
        </h4>
        <Button
          compact
          disabled={data === undefined || pageIndex === null}
          className="max-md:h-[44px]"
          onClick={() => {
            if (data !== undefined && pageIndex !== null) {
              downloadCsv(finishCsvFilename(pageIndex), buildFinishCsv(data, templates));
            }
          }}
        >
          Скачать CSV
        </Button>
      </div>

      {sheet.isPending && sheet.fetchStatus !== 'idle' && (
        <div
          role="status"
          aria-label="Загрузка ведомости"
          className="flex flex-col gap-[var(--s-3)]"
        >
          <Skeleton className="h-[20px] w-[60%]" />
          <Skeleton className="h-[16px] w-[80%]" />
        </div>
      )}
      {sheet.isError && (
        <div role="alert" className="flex flex-col gap-[var(--s-2)] text-xs text-danger">
          <span>Не удалось загрузить ведомость. {cadErrorText(sheet.error)}</span>
          <Button
            compact
            className="self-start max-md:h-[44px]"
            onClick={() => void sheet.refetch()}
          >
            Повторить
          </Button>
        </div>
      )}

      {data !== undefined && (
        <>
          <CadFinishWarnings warnings={data.warnings} zones={data.zones} onActivate={onActivate} />
          <CadFinishSheetTable
            zones={data.zones}
            templates={templates}
            activeId={activeId}
            onActivate={onActivate}
          />
          <CadFinishTotals totals={data.totals} byRoomType={data.by_room_type} />
          <p className="text-micro text-muted">
            Рабочая таблица пилота: не ВОР и не смета. Стоимости нет.
          </p>
        </>
      )}
    </section>
  );
};
