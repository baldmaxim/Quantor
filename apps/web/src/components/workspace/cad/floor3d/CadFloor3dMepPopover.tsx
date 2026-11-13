'use client';

import type { FC } from 'react';

import type { IMepInfo } from '@/lib/cad/floor3d-mep-info';

import { CadFloor3dPopoverFrame } from './CadFloor3dPopoverFrame';

interface ICadFloor3dMepPopoverProps {
  readonly info: IMepInfo;
  readonly anchor: { readonly x: number; readonly y: number };
  readonly bounds: { readonly width: number; readonly height: number };
  readonly onClose: () => void;
}

/** Карточка выбранной трассы или элемента ВИС: только просмотр. */
export const CadFloor3dMepPopover: FC<ICadFloor3dMepPopoverProps> = ({ info, anchor, bounds, onClose }) => (
  <CadFloor3dPopoverFrame title={info.title} anchor={anchor} bounds={bounds} onClose={onClose}>
    {info.rows.map((row) => (
      <p key={row.label} className="text-xs [overflow-wrap:anywhere]">
        <span className="text-muted">{row.label}: </span>
        {row.value}
      </p>
    ))}
  </CadFloor3dPopoverFrame>
);
