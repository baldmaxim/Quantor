'use client';

import type { FC } from 'react';

import { cx } from '@/components/ui';
import { layerColorVar } from '@/lib/cad/layer-colors';
import { formatInt } from '@/lib/cad/view-format';

interface ICadLayersPanelProps {
  /** Слои DXF; пусто - блока слоёв нет. */
  layers: readonly string[];
  visibleLayers: ReadonlySet<number>;
  onToggleLayer: (index: number) => void;
  opacity: number;
  onOpacityChange: (value: number) => void;
  /** Рисуется ли сейчас геометрия CAD (режим PDF её не рисует). */
  cadShown: boolean;
  /** Есть ли вообще предпросмотр DXF. */
  previewAvailable: boolean;
  pointCount: number | null;
  cropAvailable: boolean;
  cropVisible: boolean;
  onCropChange: (visible: boolean) => void;
}

const CHECK = 'flex min-h-[44px] items-center gap-[var(--s-3)] text-sm';

/** Раздел «Слои»: непрозрачность CAD, область проверки масштаба, слои DXF с цветом. */
export const CadLayersPanel: FC<ICadLayersPanelProps> = ({
  layers,
  visibleLayers,
  onToggleLayer,
  opacity,
  onOpacityChange,
  cadShown,
  previewAvailable,
  pointCount,
  cropAvailable,
  cropVisible,
  onCropChange,
}) => (
  <div className="flex min-w-0 flex-col gap-[var(--s-4)]">
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
          className="h-[44px] min-w-[120px] flex-1"
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
          className="size-5 shrink-0"
        />
        Область проверки масштаба на PDF
      </label>
    )}

    {cadShown && layers.length > 0 && (
      <fieldset className="min-w-0 border-0 p-0">
        <legend className="mb-[var(--s-2)] text-xs text-muted">Слои DXF</legend>
        <div className="flex flex-col">
          {layers.map((name, index) => {
            const on = visibleLayers.has(index);
            return (
              <label key={`${index}-${name}`} className={CHECK}>
                <input
                  type="checkbox"
                  checked={on}
                  onChange={() => onToggleLayer(index)}
                  className="size-5 shrink-0"
                />
                <span
                  aria-hidden="true"
                  data-testid="layer-swatch"
                  data-layer-on={on}
                  // Цвет слоя - динамическое значение: токен палитры по порядку слоя.
                  style={{ backgroundColor: layerColorVar(index) }}
                  className={cx(
                    'size-4 shrink-0 rounded-[var(--radius-xs)] border border-border-strong transition-opacity',
                    !on && 'opacity-30',
                  )}
                />
                <span
                  className={cx(
                    'mono text-xs [overflow-wrap:anywhere]',
                    !on && 'text-muted line-through',
                  )}
                >
                  {name}
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>
    )}

    {!cadShown && (
      <p className="text-xs text-muted" role="note">
        {previewAvailable
          ? 'Геометрия CAD не показана в режиме PDF: слои появятся в режимах «CAD» и «Наложение».'
          : 'Слоёв DXF нет: предпросмотр геометрии не получен.'}
      </p>
    )}

    {pointCount !== null && (
      <p className="text-xs text-muted">
        Точек в предпросмотре: <span className="tabular">{formatInt(pointCount)}</span>
      </p>
    )}
  </div>
);
