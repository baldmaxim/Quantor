'use client';

import type { FacadeViewRead } from '@quantor/api-client';
import type { FC } from 'react';

import { Button, StatusBadge, cx } from '@/components/ui';
import { IconReset } from '@/components/ui/icons';
import {
  EMPTY,
  FACADE_ACCEPT_BLOCKED,
  canAcceptFacade,
  facadeAxesText,
  facadeBodyText,
  facadePlaceText,
  facadeScaleText,
  facadeStatusLabel,
  markOrEmpty,
  mmOrEmpty,
} from '@/lib/cad/facades';

import type { IWorkspaceCadFacades } from './types';

interface ICadFacadeViewRowProps {
  view: FacadeViewRead;
  busy: boolean;
  active: boolean;
  onSelect: IWorkspaceCadFacades['onSelectView'];
  onOpenPage: IWorkspaceCadFacades['onOpenPage'];
  onDecide: IWorkspaceCadFacades['onDecide'];
}

const TONES = { accepted: 'success', candidate: 'accent', rejected: 'neutral' } as const;
const TH = 'px-[var(--s-2)] py-[var(--s-1)] text-left font-medium';
const TD = 'tabular mono px-[var(--s-2)] py-[var(--s-1)]';

/**
 * Вид фасада: заголовок, оси, тип, привязка по отметкам, число окон и решения человека. Раскрытие -
 * окна (высоты от ±0,000, положение от оси `axis_from`) и отметки с этажами. Щелчок по заголовку
 * открывает страницу вида в рабочей области.
 */
export const CadFacadeViewRow: FC<ICadFacadeViewRowProps> = ({
  view,
  busy,
  active,
  onSelect,
  onOpenPage,
  onDecide,
}) => {
  const acceptable = canAcceptFacade(view);
  const place = facadePlaceText(view);
  const title = view.title.trim() !== '' ? view.title : `Фасад, стр. ${view.page_index + 1}`;
  return (
    <li
      className={cx(
        'flex min-w-0 flex-col gap-[var(--s-2)] rounded-[var(--radius-sm)] border px-[var(--s-2)] py-[var(--s-2)]',
        active ? 'border-accent bg-accent-soft' : 'border-border',
      )}
      data-testid="facade-view"
    >
      <div className="flex min-w-0 items-start gap-[var(--s-2)]">
        <button
          type="button"
          title="Открыть страницу вида"
          aria-pressed={active}
          onClick={() => {
            onSelect(view.id);
            onOpenPage(view.page_index);
          }}
          className="flex min-h-[32px] min-w-0 flex-1 flex-col items-start justify-center text-left max-md:min-h-[44px]"
        >
          <span className="flex w-full min-w-0 items-center gap-x-[var(--s-2)]">
            <span className="truncate text-xs font-medium">{title}</span>
            <span className="ml-auto shrink-0">
              <StatusBadge tone={TONES[view.status]}>{facadeStatusLabel(view.status)}</StatusBadge>
            </span>
          </span>
          <span className="text-micro text-muted [overflow-wrap:anywhere]">
            {[
              facadeAxesText(view),
              place,
              facadeBodyText(view.body),
              facadeScaleText(view),
            ]
              .filter((part): part is string => part !== null)
              .join(' · ')}
          </span>
          <span className="text-micro text-muted">
            окон: {view.window_count} · этажей: {view.floors.length} · марок осей:{' '}
            {view.axes.length}
          </span>
        </button>
        <div className="flex shrink-0 gap-[var(--s-1)]">
          {view.status !== 'accepted' && (
            <Button
              compact
              iconOnly
              variant="primary"
              aria-label={`Принять: ${title}`}
              title={acceptable ? 'Принять' : FACADE_ACCEPT_BLOCKED}
              disabled={busy || !acceptable}
              onClick={() => onDecide([view.id], 'accept')}
            >
              <span aria-hidden="true">✓</span>
            </Button>
          )}
          {view.status !== 'rejected' && (
            <Button
              compact
              iconOnly
              aria-label={`Отклонить: ${title}`}
              title="Отклонить"
              disabled={busy}
              onClick={() => onDecide([view.id], 'reject')}
            >
              <span aria-hidden="true">✕</span>
            </Button>
          )}
          {view.status !== 'candidate' && (
            <Button
              compact
              iconOnly
              variant="ghost"
              aria-label={`Сбросить: ${title}`}
              title="Сбросить: вернуть в кандидаты"
              disabled={busy}
              onClick={() => onDecide([view.id], 'reset')}
            >
              <IconReset />
            </Button>
          )}
        </div>
      </div>

      {(view.windows.length > 0 || view.floors.length > 0 || view.marks.length > 0) && (
        <details className="flex min-w-0 flex-col gap-[var(--s-2)]">
          <summary className="min-h-[32px] cursor-pointer content-center text-xs text-muted max-md:min-h-[44px]">
            Окна и отметки
          </summary>
          {view.windows.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-micro" aria-label="Окна вида">
                <thead>
                  <tr className="text-muted">
                    <th className={TH}>Низ, мм</th>
                    <th className={TH}>Верх, мм</th>
                    <th className={TH}>Ширина, мм</th>
                    <th className={TH}>
                      От оси {view.axis_from ?? EMPTY}, мм
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {view.windows.map((window, index) => (
                    <tr key={index} data-testid="facade-window">
                      <td className={TD}>{mmOrEmpty(window.z_bottom_mm)}</td>
                      <td className={TD}>{mmOrEmpty(window.z_top_mm)}</td>
                      <td className={TD}>{mmOrEmpty(window.width_mm)}</td>
                      <td className={TD}>
                        {mmOrEmpty(window.u0_mm)}–{mmOrEmpty(window.u1_mm)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {view.floors.length > 0 && (
            <ul className="m-0 flex list-none flex-col gap-[var(--s-1)] p-0 text-micro">
              {view.floors.map((floor, index) => (
                <li key={`${floor.label}:${index}`} data-testid="facade-floor">
                  {floor.label} · отметка {markOrEmpty(floor.mark_mm ?? floor.label_z_mm)}
                </li>
              ))}
            </ul>
          )}
        </details>
      )}
    </li>
  );
};
