'use client';

import type { FC } from 'react';

import { CadViewTitle } from '@/components/cad/viewer/CadViewTitle';
import { cx, SegmentedControl } from '@/components/ui';
import { ToolButton } from '@/components/workspace/Toolbar';

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
          <button
            type="button"
            role="switch"
            aria-checked={floor3d.mode === '3d'}
            aria-label="Режим холста: 3D"
            title={floor3d.mode === '3d' ? 'Перейти на план' : 'Перейти в 3D'}
            onClick={() => floor3d.onModeChange(floor3d.mode === '3d' ? 'plan' : '3d')}
            className="press flex h-[36px] flex-none items-center gap-[var(--s-3)] rounded-full px-[var(--s-3)] text-sm font-medium hover:bg-surface-muted"
          >
            <span className={floor3d.mode === 'plan' ? 'text-text' : 'text-muted'}>План</span>
            <span
              aria-hidden="true"
              className={cx(
                'relative h-[22px] w-[42px] flex-none rounded-full border transition-colors duration-200',
                floor3d.mode === '3d' ? 'border-accent bg-accent' : 'border-border-control bg-surface-sunken',
              )}
            >
              <span
                className={cx(
                  'absolute top-[2px] left-[2px] h-[16px] w-[16px] rounded-full bg-surface shadow-sm transition-transform duration-200 ease-out motion-reduce:transition-none',
                  floor3d.mode === '3d' && 'translate-x-[20px]',
                )}
              />
            </span>
            <span className={floor3d.mode === '3d' ? 'text-text' : 'text-muted'}>3D</span>
          </button>
        )}
        {floor3d?.mode !== '3d' && (
          <ToolButton wide label="Вписать" hint="весь лист в экран" onClick={onFit}>
            Вписать
          </ToolButton>
        )}
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
