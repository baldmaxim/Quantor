'use client';

import type { FC } from 'react';

import { Button, SegmentedControl, type ISegmentedOption } from '@/components/ui';

export type CadViewerMode = 'pdf' | 'cad' | 'overlay';

interface ICadViewerControlsProps {
  mode: CadViewerMode;
  options: readonly ISegmentedOption<CadViewerMode>[];
  onModeChange: (mode: CadViewerMode) => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
  /** Слои DXF; пусто - блока слоёв нет. */
  layers: readonly string[];
  visibleLayers: ReadonlySet<number>;
  onToggleLayer: (index: number) => void;
  opacity: number;
  onOpacityChange: (value: number) => void;
  /** Показывать ли управление геометрией CAD (режим PDF её не рисует). */
  cadShown: boolean;
  cropAvailable: boolean;
  cropVisible: boolean;
  onCropChange: (visible: boolean) => void;
}

const CHECK = 'flex min-h-[44px] items-center gap-[var(--s-3)] text-sm';

export const CadViewerControls: FC<ICadViewerControlsProps> = ({
  mode,
  options,
  onModeChange,
  onZoomIn,
  onZoomOut,
  onFit,
  layers,
  visibleLayers,
  onToggleLayer,
  opacity,
  onOpacityChange,
  cadShown,
  cropAvailable,
  cropVisible,
  onCropChange,
}) => (
  <div className="flex min-w-0 flex-col gap-[var(--s-4)]">
    <div className="flex flex-wrap items-center gap-[var(--s-4)]">
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

    {cadShown && (
      <label className="flex min-h-[44px] flex-wrap items-center gap-x-[var(--s-4)] text-sm">
        <span>Непрозрачность CAD</span>
        <input
          type="range"
          min={0.1}
          max={1}
          step={0.05}
          value={opacity}
          onChange={(event) => onOpacityChange(Number(event.target.value))}
          aria-valuetext={`${Math.round(opacity * 100)} %`}
          className="h-[44px] min-w-[140px] flex-1"
        />
        <span className="tabular w-[4ch] text-xs text-muted">{Math.round(opacity * 100)} %</span>
      </label>
    )}

    {cropAvailable && (
      <label className={CHECK}>
        <input
          type="checkbox"
          checked={cropVisible}
          onChange={(event) => onCropChange(event.target.checked)}
          className="size-5"
        />
        Область проверки масштаба на PDF
      </label>
    )}

    {cadShown && layers.length > 0 && (
      <fieldset className="min-w-0 border-0 p-0">
        <legend className="mb-[var(--s-2)] text-xs text-muted">Слои DXF</legend>
        <div className="scroll-area flex max-h-[220px] flex-col overflow-auto overscroll-contain">
          {layers.map((name, index) => (
            <label key={`${index}-${name}`} className={CHECK}>
              <input
                type="checkbox"
                checked={visibleLayers.has(index)}
                onChange={() => onToggleLayer(index)}
                className="size-5 shrink-0"
              />
              <span className="mono text-xs [overflow-wrap:anywhere]">{name}</span>
            </label>
          ))}
        </div>
      </fieldset>
    )}
  </div>
);
