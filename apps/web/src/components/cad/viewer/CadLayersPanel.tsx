'use client';

import { useMemo, type FC } from 'react';

import { groupLayers } from '@/lib/cad/layer-groups';
import { formatInt } from '@/lib/cad/view-format';
import { MAX_PDF_OPACITY, MIN_PDF_OPACITY } from '@/lib/cad/view-mode';

import { CadLayerGroup } from './CadLayerGroup';

interface ICadLayersPanelProps {
  /** Слои DXF; пусто - блока слоёв нет. */
  layers: readonly string[];
  visibleLayers: ReadonlySet<number>;
  onToggleLayer: (index: number) => void;
  /** Скрыть или показать несколько слоёв разом (переключатель группы). */
  onSetLayersHidden: (indices: readonly number[], hidden: boolean) => void;
  /** Непрозрачность подложки PDF, 0-1: DXF всегда непрозрачный. */
  pdfOpacity: number;
  onPdfOpacityChange: (value: number) => void;
  /** Ползунок действует, только когда DXF наложен на лист: иначе PDF показан целиком. */
  pdfOpacityActive: boolean;
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

/** Раздел «Слои»: непрозрачность PDF, область проверки масштаба, слои DXF с цветом. */
export const CadLayersPanel: FC<ICadLayersPanelProps> = ({
  layers,
  visibleLayers,
  onToggleLayer,
  onSetLayersHidden,
  pdfOpacity,
  onPdfOpacityChange,
  pdfOpacityActive,
  cadShown,
  previewAvailable,
  pointCount,
  cropAvailable,
  cropVisible,
  onCropChange,
}) => {
  const groups = useMemo(() => groupLayers(layers), [layers]);

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-4)]">
      {previewAvailable && (
        <div className="flex min-w-0 flex-col">
          <label className="flex min-h-[44px] flex-wrap items-center gap-x-[var(--s-4)] text-sm">
            <span>Непрозрачность PDF</span>
            <input
              type="range"
              min={MIN_PDF_OPACITY}
              max={MAX_PDF_OPACITY}
              step={0.05}
              value={pdfOpacity}
              disabled={!pdfOpacityActive}
              onChange={(event) => onPdfOpacityChange(Number(event.target.value))}
              aria-valuetext={`${Math.round(pdfOpacity * 100)} %`}
              className="h-[44px] min-w-[120px] flex-1"
            />
            <span className="tabular w-[4ch] text-xs text-muted">
              {Math.round(pdfOpacity * 100)} %
            </span>
          </label>
          {!pdfOpacityActive && (
            <p className="text-xs text-muted">Ползунок действует, когда DXF наложен на лист.</p>
          )}
        </div>
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
            {groups.map((group) => (
              <CadLayerGroup
                key={group.key}
                group={group}
                layers={layers}
                visibleLayers={visibleLayers}
                onToggleLayer={onToggleLayer}
                onSetLayersHidden={onSetLayersHidden}
              />
            ))}
          </div>
        </fieldset>
      )}

      {!cadShown && (
        <p className="text-xs text-muted" role="note">
          {previewAvailable
            ? 'Геометрия CAD пока не наложена на лист: слои появятся, когда DXF можно показать.'
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
};
