'use client';

import { useEffect, useRef, type FC } from 'react';

import { ToolButton } from '@/components/workspace/Toolbar';
import type { FloorTitleLike } from '@/lib/cad/floor-title';
import { useFloor3dDxf } from '@/lib/cad/floor3d-dxf';
import type { ICadViewParams } from '@/lib/cad/view-queries';

export interface ICadFloor3dDxfButtonProps {
  readonly params: ICadViewParams;
  /** Текущая модель этажа: при её смене прежний DXF устарел. */
  readonly model: unknown;
  /** Заголовок плана листа: по нему называется скачиваемый файл. */
  readonly title?: FloorTitleLike;
  readonly disabled: boolean;
  /** В модели есть отверстия-кандидаты без решения. */
  readonly hasCandidates: boolean;
}

/**
 * Кнопка «Скачать 3D DXF»: ставит задание, ждёт его и сама начинает скачивание. Готовый файл
 * остаётся ссылкой «Скачать ещё раз», повторный POST до смены модели не нужен.
 */
export const CadFloor3dDxfButton: FC<ICadFloor3dDxfButtonProps> = ({
  params,
  model,
  title,
  disabled,
  hasCandidates,
}) => {
  const dxf = useFloor3dDxf(params, model, title);
  const link = useRef<HTMLAnchorElement>(null);
  const downloaded = useRef<string | null>(null);

  useEffect(() => {
    if (dxf.readyJobId === null) {
      downloaded.current = null;
      return;
    }
    if (downloaded.current === dxf.readyJobId) return;
    downloaded.current = dxf.readyJobId;
    link.current?.click();
  }, [dxf.readyJobId]);

  const preparing = dxf.phase === 'preparing';
  const label = preparing ? 'Готовим DXF…' : dxf.phase === 'failed' ? 'Повторить' : 'Скачать 3D DXF';
  const hint =
    hasCandidates && dxf.phase !== 'failed'
      ? 'отверстия-кандидаты войдут в DXF как отверстия'
      : 'трёхмерный DXF для AutoCAD';
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-[var(--s-2)] gap-y-[var(--s-1)]">
      {dxf.phase === 'ready' ? (
        <a
          ref={link}
          href={dxf.url ?? undefined}
          download={dxf.fileName}
          className="press flex h-[var(--h-ctl-ws)] flex-none items-center rounded-[var(--radius-sm)] px-[var(--s-4)] text-xs whitespace-nowrap text-accent hover:bg-surface-muted"
        >
          Скачать ещё раз
        </a>
      ) : (
        <ToolButton wide label={label} hint={hint} disabled={disabled || preparing} onClick={dxf.start}>
          {label}
        </ToolButton>
      )}
      {dxf.phase === 'failed' && dxf.error !== null && (
        <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
          {dxf.error}
        </p>
      )}
    </div>
  );
};
