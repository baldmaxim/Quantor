'use client';

import type { FC, ReactNode } from 'react';

import { Button, SegmentedControl, type ISegmentedOption } from '@/components/ui';

export type CadViewerMode = 'pdf' | 'cad' | 'overlay';

interface ICadViewerControlsProps {
  /** Компактный заголовок вида: «Стр. 81 · вид 1» и бейдж итога. */
  heading: ReactNode;
  mode: CadViewerMode;
  options: readonly ISegmentedOption<CadViewerMode>[];
  onModeChange: (mode: CadViewerMode) => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
}

/** Строка над холстом: заголовок, режим показа, масштаб вида. Остальное - в боковой панели. */
export const CadViewerControls: FC<ICadViewerControlsProps> = ({
  heading,
  mode,
  options,
  onModeChange,
  onZoomIn,
  onZoomOut,
  onFit,
}) => (
  <div className="flex min-w-0 flex-wrap items-center gap-x-[var(--s-5)] gap-y-[var(--s-3)]">
    <div className="min-w-0">{heading}</div>
    <SegmentedControl
      label="Что показывать"
      value={mode}
      options={options}
      onChange={onModeChange}
    />
    <div className="flex items-center gap-[var(--s-2)]" role="group" aria-label="Масштаб вида">
      <Button iconOnly onClick={onZoomOut} aria-label="Уменьшить" title="Уменьшить">
        −
      </Button>
      <Button iconOnly onClick={onZoomIn} aria-label="Увеличить" title="Увеличить">
        +
      </Button>
      <Button onClick={onFit}>Вписать</Button>
    </div>
  </div>
);
