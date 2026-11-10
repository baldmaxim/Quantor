'use client';

import type { FC } from 'react';

import { CadViewTitle } from '@/components/cad/viewer/CadViewTitle';
import { CadViewerControls } from '@/components/cad/viewer/CadViewerControls';
import { SegmentedControl, type ISegmentedOption } from '@/components/ui';
import type { CadViewMode } from '@/lib/cad/view-mode';

import type { IWorkspaceCadBarProps } from './types';

/**
 * Строка над холстом рабочей области на вкладке CAD: заголовок вида, режим показа (PDF, CAD,
 * наложение), масштаб камеры. Холст один - рабочей области, своего у строки нет.
 */
export const WorkspaceCadBar: FC<IWorkspaceCadBarProps> = ({
  diagnostics,
  views,
  view,
  onViewChange,
  mode,
  dxfAvailable,
  dxfReason,
  onModeChange,
  onZoomIn,
  onZoomOut,
  onFit,
  notices,
  loading,
}) => {
  // DXF накладывается на лист по кадру координат, поэтому «CAD» и «Наложение» доступны вместе.
  const options: readonly ISegmentedOption<CadViewMode>[] = [
    { value: 'pdf', label: 'PDF' },
    {
      value: 'cad',
      label: 'CAD',
      disabled: !dxfAvailable,
      hint: dxfAvailable ? undefined : (dxfReason ?? undefined),
    },
    {
      value: 'overlay',
      label: 'Наложение',
      disabled: !dxfAvailable,
      hint: dxfAvailable ? undefined : (dxfReason ?? undefined),
    },
  ];

  return (
    <div
      data-testid="workspace-cad-bar"
      className="flex flex-none flex-col gap-[var(--s-2)] border-b border-border bg-surface px-[var(--s-5)] py-[var(--s-3)]"
    >
      <CadViewerControls
        heading={
          <div className="flex min-w-0 flex-wrap items-center gap-x-[var(--s-4)] gap-y-[var(--s-2)]">
            <CadViewTitle diagnostics={diagnostics} />
            {views.length > 1 && view !== null && (
              <SegmentedControl
                label="Вид листа"
                value={view}
                options={views.map((item) => ({ value: item, label: `Вид ${item}` }))}
                onChange={onViewChange}
              />
            )}
          </div>
        }
        mode={mode}
        options={options}
        onModeChange={onModeChange}
        onZoomIn={onZoomIn}
        onZoomOut={onZoomOut}
        onFit={onFit}
      />
      {(notices.length > 0 || loading) && (
        <div className="flex max-h-[96px] flex-col gap-[var(--s-2)] overflow-auto overscroll-contain">
          {notices.map((notice) => (
            <p
              key={notice.text}
              role={notice.tone === 'alert' ? 'alert' : 'note'}
              className={
                notice.tone === 'alert'
                  ? 'text-xs text-danger [overflow-wrap:anywhere]'
                  : 'text-xs text-muted [overflow-wrap:anywhere]'
              }
            >
              {notice.text}
            </p>
          ))}
          {loading && (
            <p role="status" className="text-xs text-muted">
              Загрузка геометрии CAD…
            </p>
          )}
        </div>
      )}
    </div>
  );
};
