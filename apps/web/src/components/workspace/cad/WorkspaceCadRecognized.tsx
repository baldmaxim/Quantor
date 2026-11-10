'use client';

import Link from 'next/link';
import type { FC } from 'react';

import { CadRemarksPanel } from '@/components/cad/viewer/CadRemarksPanel';
import { ErrorState, SegmentedControl, Skeleton, StatusBadge } from '@/components/ui';
import { resultInfo } from '@/lib/cad/stages';
import { formatDeviationPercent, scaleStatusInfo } from '@/lib/cad/view-format';

import type { IWorkspaceCadRecognized } from './types';

export const CAD_LINK_CLASS =
  'inline-flex min-h-[44px] items-center text-sm text-accent underline underline-offset-4';

interface IWorkspaceCadRecognizedProps {
  model: IWorkspaceCadRecognized;
  cadHref: string;
}

/** Лист с результатом CAD: итог, масштаб, вид, переключатель наложения и замечания. */
export const WorkspaceCadRecognized: FC<IWorkspaceCadRecognizedProps> = ({ model, cadHref }) => {
  const { diagnostics } = model;

  if (model.error) {
    return (
      <ErrorState
        title="Результат CAD не загружен"
        code={model.error.code}
        description={model.error.text}
      />
    );
  }

  if (model.loading) {
    return (
      <div className="flex flex-col gap-[var(--s-4)]" role="status" aria-label="Загрузка вида">
        <Skeleton className="h-[20px] w-[60%]" />
        <Skeleton className="h-[16px] w-[80%]" />
        <Skeleton className="h-[44px] w-full" />
      </div>
    );
  }

  if (!diagnostics) {
    return <p className="text-xs text-muted">В задании нет видов этого листа.</p>;
  }

  const info = resultInfo(model.resultStatus ?? diagnostics.result_status);
  const scale = scaleStatusInfo(diagnostics.scale?.status ?? diagnostics.scale_status);

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-5)]" data-testid="workspace-cad-result">
      <div className="flex min-w-0 flex-col gap-[var(--s-3)]">
        {info && (
          <StatusBadge tone={info.tone} dot={false} wrap>
            {info.label}
          </StatusBadge>
        )}
        <p className="text-xs text-muted">Инженерная приёмка: не выполнена</p>
        <p className="flex flex-wrap items-center gap-x-[var(--s-3)] gap-y-[var(--s-2)] text-xs">
          <span className="text-muted">Масштаб</span>
          <StatusBadge tone={scale.tone} dot={false}>
            {scale.label}
          </StatusBadge>
          <span className="text-muted">
            отклонение от цепочек{' '}
            <span className="tabular text-text">
              {formatDeviationPercent(diagnostics.scale?.deviation)}
            </span>
          </span>
        </p>
      </div>

      {model.views.length > 1 && model.view !== null && (
        <SegmentedControl
          label="Вид листа"
          layout="wrap"
          value={model.view}
          options={model.views.map((view) => ({
            value: view,
            label: `Вид ${view}`,
          }))}
          onChange={model.onViewChange}
        />
      )}

      <div className="flex min-w-0 flex-col gap-[var(--s-2)]">
        <label className="flex min-h-[44px] cursor-pointer items-center gap-[var(--s-4)] text-sm">
          <input
            type="checkbox"
            checked={model.overlay && model.overlayAvailable}
            disabled={!model.overlayAvailable}
            onChange={(event) => model.onOverlayChange(event.target.checked)}
            className="size-5 shrink-0 accent-accent"
          />
          DXF поверх чертежа
        </label>
        {model.overlayReason && (
          <p className="text-xs text-muted" role="note">
            {model.overlayReason}
          </p>
        )}
        {model.overlayLoading && (
          <p className="text-xs text-muted" role="status">
            Загрузка геометрии CAD…
          </p>
        )}
        {model.overlayError && (
          <p className="text-xs text-danger" role="alert">
            {model.overlayError}
          </p>
        )}
      </div>

      <Link href={cadHref} className={CAD_LINK_CLASS}>
        Открыть на странице CAD
      </Link>

      {model.remarks && <CadRemarksPanel {...model.remarks} />}
    </div>
  );
};
