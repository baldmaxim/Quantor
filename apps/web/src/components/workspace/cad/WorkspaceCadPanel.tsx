'use client';

import Link from 'next/link';
import type { FC } from 'react';

import { Button, SkeletonRows, StatusBadge } from '@/components/ui';

import type { IWorkspaceCadPanelProps } from './types';
import { CAD_LINK_CLASS, WorkspaceCadRecognized } from './WorkspaceCadRecognized';

/**
 * Вкладка «CAD» левой панели рабочей области: что известно о текущем листе.
 *
 * Лист не преобразовывался, идёт, завершился ошибкой или распознан - четыре состояния, у каждого
 * свой бейдж и ссылка на страницу CAD. Данные и слой на холсте даёт `useWorkspaceCad`.
 */
export const WorkspaceCadPanel: FC<IWorkspaceCadPanelProps> = ({
  state,
  sheetLabel,
  cadHref,
  loadError,
  onRetry,
  recognized,
}) => (
  <div
    className="flex min-w-0 flex-col gap-[var(--s-5)] p-[var(--s-5)]"
    data-testid="workspace-cad"
  >
    {sheetLabel !== null && (
      <p className="text-xs text-muted">
        Лист <span className="text-text">{sheetLabel}</span>
      </p>
    )}

    {state === 'no-sheet' && <p className="text-xs text-muted">Лист не выбран.</p>}

    {state === 'loading' && (
      <div role="status" aria-label="Загрузка заданий CAD">
        <SkeletonRows rows={3} />
      </div>
    )}

    {state === 'error' && (
      <div role="alert" className="flex flex-col gap-[var(--s-3)] text-xs text-danger">
        <span>Не удалось загрузить задания CAD. {loadError}</span>
        <Button compact onClick={onRetry} className="self-start max-md:h-[44px]">
          Повторить
        </Button>
      </div>
    )}

    {state === 'none' && (
      <>
        <p className="text-sm">Лист не преобразовывался</p>
        <Link href={cadHref} className={CAD_LINK_CLASS}>
          Открыть страницу CAD
        </Link>
      </>
    )}

    {state === 'running' && (
      <>
        <div>
          <StatusBadge tone="accent" dot={false}>
            Выполняется
          </StatusBadge>
        </div>
        <p className="text-xs text-muted">Результат появится здесь, когда задание завершится.</p>
        <Link href={cadHref} className={CAD_LINK_CLASS}>
          Открыть задание на странице CAD
        </Link>
      </>
    )}

    {state === 'failed' && (
      <>
        <div>
          <StatusBadge tone="danger" dot={false}>
            Ошибка
          </StatusBadge>
        </div>
        <Link href={cadHref} className={CAD_LINK_CLASS}>
          Открыть задание на странице CAD
        </Link>
      </>
    )}

    {state === 'recognized' && recognized && (
      <WorkspaceCadRecognized model={recognized} cadHref={cadHref} />
    )}
  </div>
);
