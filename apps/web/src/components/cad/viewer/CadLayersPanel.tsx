'use client';

import { useMemo, type FC } from 'react';

import { categoryOfLayer, type CadExtraCategory } from '@/lib/cad/layer-categories';
import { groupLayers } from '@/lib/cad/layer-groups';
import { mepColorVar } from '@/lib/cad/mep-layers';
import { formatInt } from '@/lib/cad/view-format';
import { MAX_PDF_OPACITY, MIN_PDF_OPACITY } from '@/lib/cad/view-mode';
import { useWorkspaceStore } from '@/store/workspace';

import { CadLayerGroup } from './CadLayerGroup';
import { CadZoneLayers, type ICadZoneLayers } from './CadZoneLayers';

interface ICadLayersPanelProps {
  /** Слои DXF; пусто - блока слоёв нет. */
  layers: readonly string[];
  visibleLayers: ReadonlySet<number>;
  onToggleLayer: (index: number) => void;
  /** Скрыть или показать несколько слоёв разом (переключатель группы). */
  onSetLayersHidden: (indices: readonly number[], hidden: boolean) => void;
  /** Открыт режим «3D»: слои без категории конструкций недоступны («только план»). */
  mode3d?: boolean;
  /** Строки «Плита» и «Перемычки» без слоя DXF; нет - строк нет. */
  categories?: {
    slab: boolean;
    lintel: boolean;
    onChange: (category: CadExtraCategory, visible: boolean) => void;
  } | null;
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
  /** Полный показ контуров конструкций (без него - только выбранные); нет - переключателя нет. */
  constructions?: {
    visible: boolean;
    onVisibleChange: (visible: boolean) => void;
  } | null;
  /** Зоны листа (цвет по типу, скрытие, подписи); нет - блока нет. */
  zones?: ICadZoneLayers | null;
  /** Разметка разрезов на листе (вкл/выкл); нет - на листе разрезов нет. */
  sections?: { visible: boolean; onVisibleChange: (visible: boolean) => void } | null;
  /** Трассы механики выбранного route-задания; нет - группы нет. */
  mep?: {
    /** Имена слоёв DXF трасс. */
    names: readonly string[];
    /** Подписи пунктов, по одной на имя. */
    titles: readonly string[];
    visible: ReadonlySet<number>;
    onToggle: (index: number) => void;
    onSetHidden: (indices: readonly number[], hidden: boolean) => void;
  } | null;
}

const MEP_GROUP = 'mep';

const CHECK = 'flex min-h-[44px] items-center gap-[var(--s-3)] text-sm';

/** Раздел «Слои»: непрозрачность PDF, область проверки масштаба, слои DXF с цветом. */
export const CadLayersPanel: FC<ICadLayersPanelProps> = ({
  layers,
  visibleLayers,
  onToggleLayer,
  onSetLayersHidden,
  mode3d = false,
  categories = null,
  pdfOpacity,
  onPdfOpacityChange,
  pdfOpacityActive,
  cadShown,
  previewAvailable,
  pointCount,
  cropAvailable,
  cropVisible,
  onCropChange,
  constructions = null,
  zones = null,
  sections = null,
  mep = null,
}) => {
  const groups = useMemo(() => groupLayers(layers), [layers]);
  // В 3D доступны только слои с категорией конструкций: остальные - «только план».
  const planOnly = useMemo<ReadonlySet<number>>(
    () =>
      new Set(
        mode3d ? layers.flatMap((name, index) => (categoryOfLayer(name) === null ? [index] : [])) : [],
      ),
    [mode3d, layers],
  );
  // Показ распознанных блоков один на всё окно: тот же флаг, что у кнопки панели инструментов.
  const regionsVisible = useWorkspaceStore((state) => state.overlayVisible);
  const toggleRegions = useWorkspaceStore((state) => state.toggleOverlay);

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-4)]">
      <div className="flex min-w-0 flex-col">
        <label className={CHECK}>
          <input
            type="checkbox"
            checked={regionsVisible}
            onChange={toggleRegions}
            className="size-5 shrink-0"
          />
          Распознанные блоки
        </label>
        <p className="text-xs text-muted">Области распознавания поверх PDF</p>
      </div>

      {constructions && (
        <div className="flex min-w-0 flex-col">
          <label className={CHECK}>
            <input
              type="checkbox"
              checked={constructions.visible}
              onChange={(event) => constructions.onVisibleChange(event.target.checked)}
              className="size-5 shrink-0"
            />
            Контуры всех конструкций
          </label>
          <p className="text-xs text-muted">Без галки рисуются только выбранные конструкции</p>
        </div>
      )}

      {sections && (
        <div className="flex min-w-0 flex-col">
          <label className={CHECK}>
            <input
              type="checkbox"
              checked={sections.visible}
              onChange={(event) => sections.onVisibleChange(event.target.checked)}
              className="size-5 shrink-0"
            />
            Разметка разрезов
          </label>
          <p className="text-xs text-muted">Отметки, полосы и размеры уровней на листе-разрезе</p>
        </div>
      )}

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

      {categories && (
        <fieldset className="min-w-0 border-0 p-0" data-testid="category-layers">
          <legend className="mb-[var(--s-2)] text-xs text-muted">Конструкции листа</legend>
          <label className={CHECK}>
            <input
              type="checkbox"
              checked={categories.slab}
              onChange={(event) => categories.onChange('slab', event.target.checked)}
              className="size-5 shrink-0"
            />
            Плита
          </label>
          <label className={CHECK}>
            <input
              type="checkbox"
              checked={categories.lintel}
              onChange={(event) => categories.onChange('lintel', event.target.checked)}
              className="size-5 shrink-0"
            />
            Перемычки
            {!mode3d && <span className="ml-auto text-xs text-muted">только 3D</span>}
          </label>
        </fieldset>
      )}

      {cadShown && layers.length > 0 && (
        <fieldset className="min-w-0 border-0 p-0">
          <legend className="mb-[var(--s-2)] text-xs text-muted">Чертёж (DXF вида)</legend>
          <div className="flex flex-col">
            {groups.map((group) => (
              <CadLayerGroup
                key={group.key}
                group={group}
                layers={layers}
                visibleLayers={visibleLayers}
                onToggleLayer={onToggleLayer}
                onSetLayersHidden={onSetLayersHidden}
                disabledIndices={planOnly}
                disabledNote="только план"
              />
            ))}
          </div>
        </fieldset>
      )}

      {zones && zones.categories.length > 0 && (
        <fieldset disabled={mode3d} className="min-w-0 border-0 p-0 disabled:opacity-60">
          <CadZoneLayers {...zones} />
          {mode3d && <p className="text-xs text-muted">Зоны: только план</p>}
        </fieldset>
      )}

      {mep && (
        <fieldset className="min-w-0 border-0 p-0" data-testid="mep-layers">
          <legend className="sr-only">Слои трасс механики</legend>
          <CadLayerGroup
            group={{
              key: MEP_GROUP,
              label: 'Трассы механики',
              indices: mep.names.map((_, index) => index),
            }}
            layers={mep.titles}
            visibleLayers={mep.visible}
            onToggleLayer={mep.onToggle}
            onSetLayersHidden={(indices, hidden) => mep.onSetHidden(indices, hidden)}
            swatchColor={(index) => mepColorVar(mep.names[index] ?? '')}
          />
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
