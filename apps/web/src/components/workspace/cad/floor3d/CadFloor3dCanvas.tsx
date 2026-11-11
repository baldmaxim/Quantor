'use client';

import { useEffect, useRef, useState, type FC } from 'react';

import {
  createFloor3dEngine,
  type Floor3dViewKind,
  type IFloor3dEngine,
  type IFloor3dMeasureState,
  type IFloor3dSnapState,
} from '@/lib/cad/floor3d-engine';
import { highlightOf, highlightsOf, visibilityOf, type IFloor3dPlan } from '@/lib/cad/floor3d-geometry';
import {
  buildFloor3dRoutes,
  readFloor3dRouteColors,
  type IFloor3dRoutePolyline,
} from '@/lib/cad/floor3d-routes';
import { buildFloor3dScene, readFloor3dColors, type IFloor3dPick } from '@/lib/cad/floor3d-scene';
import { EXTRA_CATEGORIES, type CadLayerCategory } from '@/lib/cad/layer-categories';
import { isMepLayerHidden } from '@/lib/cad/mep-layers';
import { useTheme } from '@/lib/theme';

import { CadFloor3dMeasureLabel } from './CadFloor3dMeasureLabel';
import { CadFloor3dSnapLabel } from './CadFloor3dSnapLabel';

/** Запрос камеры: `seq` меняется при каждом нажатии, чтобы повторная команда не терялась. */
export interface IFloor3dViewRequest {
  readonly kind: Floor3dViewKind | 'fit';
  readonly seq: number;
}

/** Трассы механики листа: полилинии в мм DXF, Z от отметки этажа модели. */
export interface ICadFloor3dRoutes {
  readonly polylines: readonly IFloor3dRoutePolyline[];
  /** Отметка этажа модели (`base_z_mm`), мм. */
  readonly baseZMm: number;
}

interface ICadFloor3dCanvasProps {
  readonly plan: IFloor3dPlan;
  /** Трассы механики; `null` - трасс нет. */
  readonly routes?: ICadFloor3dRoutes | null;
  /** Маска слоёв трасс, скрытых человеком (общая с 2D). */
  readonly hiddenRoutesMask?: number;
  readonly showSlabCap: boolean;
  readonly viewRequest: IFloor3dViewRequest | null;
  /** Выбранный элемент: подсвечивается оверлеем. */
  readonly selected: IFloor3dPick | null;
  /** Общий выбор конструкций (план и 3D): стены и плита подсвечиваются все. */
  readonly selectedIds?: ReadonlySet<string>;
  /** Скрытые категории (вкладка «Слои»): скрываются без пересборки сцены. */
  readonly hiddenCategories?: ReadonlySet<CadLayerCategory>;
  /** Скрытые конструкции (все слои-источники скрыты): подгруппы сцены скрываются без пересборки. */
  readonly hiddenConstructionIds?: ReadonlySet<string>;
  /** Ключ подгруппы конструкции по слоям-источникам; смена пересобирает сцену. */
  readonly groupKeyOf?: (id: string) => string | undefined;
  /** Режим измерения: клики ставят точки, элемент не выбирается. */
  readonly measuring: boolean;
  readonly onPick: (pick: IFloor3dPick | null, anchor: { x: number; y: number }) => void;
  readonly onMove: () => void;
  /** Холст создать не удалось (нет WebGL). */
  readonly onError: (message: string) => void;
}

const NO_ROUTES_MASK = 0;
const NO_IDS: ReadonlySet<string> = new Set<string>();
const NO_CATEGORIES: ReadonlySet<CadLayerCategory> = new Set<CadLayerCategory>();
const ALL_CATEGORIES: readonly CadLayerCategory[] = [
  'masonry',
  'monolith',
  'frame_partition',
  'door',
  ...EXTRA_CATEGORIES,
];

/** Категории, чьи меши сцена делит на подгруппы по слоям-источникам. */
const LAYER_SPLIT: ReadonlySet<CadLayerCategory> = new Set<CadLayerCategory>([
  'masonry',
  'monolith',
  'frame_partition',
]);

/**
 * Холст three.js: владеет renderer'ом и освобождает его при размонтировании. Модель пересобирается
 * при смене плана, темы и галки «Плита сверху»; камера при этом не сбрасывается.
 */
export const CadFloor3dCanvas: FC<ICadFloor3dCanvasProps> = ({
  plan,
  routes = null,
  hiddenRoutesMask = NO_ROUTES_MASK,
  showSlabCap,
  viewRequest,
  selected,
  selectedIds = NO_IDS,
  hiddenCategories = NO_CATEGORIES,
  hiddenConstructionIds = NO_IDS,
  groupKeyOf,
  measuring,
  onPick,
  onMove,
  onError,
}) => {
  const host = useRef<HTMLDivElement>(null);
  const engine = useRef<IFloor3dEngine | null>(null);
  const theme = useTheme();
  const [measure, setMeasure] = useState<IFloor3dMeasureState | null>(null);
  const [snap, setSnap] = useState<IFloor3dSnapState | null>(null);

  // Колбэки читаются в момент события: смена пропсов движок не пересоздаёт.
  const handlers = useRef({ onPick, onMove, onError });
  useEffect(() => {
    handlers.current = { onPick, onMove, onError };
  });

  useEffect(() => {
    const element = host.current;
    if (element === null) return undefined;
    try {
      engine.current = createFloor3dEngine(element, {
        reducedMotion: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
        onPick: (pick, anchor) => handlers.current.onPick(pick, anchor),
        onMove: () => handlers.current.onMove(),
        onMeasure: setMeasure,
        onSnap: setSnap,
      });
    } catch {
      handlers.current.onError('Не удалось запустить 3D: в браузере недоступен WebGL.');
      return undefined;
    }
    return () => {
      engine.current?.dispose();
      engine.current = null;
    };
  }, []);

  useEffect(() => {
    engine.current?.setModel(
      plan.prisms.length === 0
        ? null
        : buildFloor3dScene(plan, readFloor3dColors(), { showSlabCap, groupKeyOf }),
    );
  }, [plan, showSlabCap, theme, groupKeyOf]);

  // Трассы механики: отдельная группа сцены, пересобирается при смене данных, плана и темы.
  const routeScene = useRef<ReturnType<typeof buildFloor3dRoutes> | null>(null);
  useEffect(() => {
    if (routes === null || routes.polylines.length === 0) {
      routeScene.current = null;
      engine.current?.setRoutes(null);
      return;
    }
    const built = buildFloor3dRoutes(routes.polylines, readFloor3dRouteColors(), {
      center: plan.center,
      baseZMm: routes.baseZMm,
    });
    routeScene.current = built;
    engine.current?.setRoutes(built);
  }, [routes, plan.center, theme]);

  // Видимость слоёв трасс - после пересборки (эффект выше): та же маска, что у слоёв трасс в 2D.
  useEffect(() => {
    const built = routeScene.current;
    if (built === null) return;
    for (const polyline of routes?.polylines ?? []) {
      built.setLayerVisible(polyline.layer, !isMepLayerHidden(hiddenRoutesMask, polyline.layer));
    }
    engine.current?.refresh();
  }, [routes, plan.center, theme, hiddenRoutesMask]);

  // Видимость категорий - после пересборки модели (эффект выше); сцена при этом не пересобирается.
  useEffect(() => {
    for (const category of ALL_CATEGORIES) {
      engine.current?.setCategoryVisible(category, !hiddenCategories.has(category));
    }
  }, [plan, showSlabCap, theme, hiddenCategories]);

  // Скрытые слоями конструкции: движок помнит набор и применяет его к каждой новой модели.
  useEffect(() => {
    engine.current?.setHiddenIds(hiddenConstructionIds);
  }, [hiddenConstructionIds]);

  // Выделение накладывается после пересборки модели (эффект выше) и при смене выбора: общий выбор
  // конструкций плюс локальный (перемычка, дверь, отверстие). Скрытое категорией не подсвечивается.
  useEffect(() => {
    const local = highlightOf(plan, selected);
    const targets = [...highlightsOf(plan, selectedIds), ...(local === null ? [] : [local])].filter(
      (target) => {
        if (target.kind === 'hole') return !hiddenCategories.has('slab');
        const category = visibilityOf(target.spec);
        if (hiddenCategories.has(category)) return false;
        // Подгруппы по слоям есть только у кладки, монолита и перегородок.
        return !(LAYER_SPLIT.has(category) && hiddenConstructionIds.has(target.spec.id));
      },
    );
    engine.current?.setHighlight(targets);
  }, [plan, showSlabCap, theme, selected, selectedIds, hiddenCategories, hiddenConstructionIds]);

  useEffect(() => {
    engine.current?.setMeasuring(measuring);
  }, [measuring]);

  useEffect(() => {
    if (viewRequest === null) return;
    if (viewRequest.kind === 'fit') engine.current?.fit();
    else engine.current?.setView(viewRequest.kind);
  }, [viewRequest]);

  const [first, second] = measure?.points ?? [];
  return (
    <div className="relative h-full w-full">
      <div ref={host} role="img" aria-label="3D-модель этажа" className="h-full w-full" />
      {measuring && first !== undefined && second !== undefined && measure?.mid && (
        <CadFloor3dMeasureLabel a={first} b={second} center={plan.center} at={measure.mid} />
      )}
      {measuring && snap !== null && <CadFloor3dSnapLabel snap={snap} />}
    </div>
  );
};
