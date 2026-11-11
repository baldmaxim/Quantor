'use client';

import type { FC } from 'react';

import { CadViewTitle } from '@/components/cad/viewer/CadViewTitle';
import { Button, SegmentedControl } from '@/components/ui';

import type { IWorkspaceCadBarProps } from './types';

/**
 * Строка над холстом рабочей области на вкладке CAD: заголовок вида, переключатель видов и
 * «Вписать». DXF всегда показан наложением на PDF. Холст один - рабочей области, своего у строки нет.
 */
export const WorkspaceCadBar: FC<IWorkspaceCadBarProps> = ({
  diagnostics,
  views,
  view,
  onViewChange,
  onFit,
  notices,
  loading,
  floor3d = null,
}) => {
  return (
    <div
      data-testid="workspace-cad-bar"
      className="flex flex-none flex-col gap-[var(--s-2)] border-b border-border bg-surface px-[var(--s-5)] py-[var(--s-3)]"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-[var(--s-5)] gap-y-[var(--s-3)]">
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
        {floor3d && (
          <SegmentedControl
            label="Режим холста"
            value={floor3d.mode}
            options={[
              { value: 'plan', label: 'План' },
              { value: '3d', label: '3D' },
            ]}
            onChange={floor3d.onModeChange}
          />
        )}
        {floor3d?.mode !== '3d' && <Button onClick={onFit}>Вписать</Button>}
      </div>
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
