import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

import type {
  HostCategoryOf,
  IFloor3dHighlight,
  IFloor3dPlan,
  IHoleSpec,
  IPrismSpec,
  Point2,
  PrismCategory,
} from './floor3d-geometry';
import { itemAtTriangle, visibilityOf } from './floor3d-geometry';
import type { CadLayerCategory } from './layer-categories';

/**
 * Сцена 3D-вида этажа (ADR-0039): three.js-объекты по плану из `floor3d-geometry`. Модуль грузится
 * только вместе с видом «3D»: `three` не попадает в общий чанк маршрута.
 *
 * Меши и клик. Призмы одной категории сливаются в один меш (плита, кладка, монолит, перемычки,
 * двери - пять вызовов отрисовки вместо сотен). Соответствие «треугольник -> элемент» хранится в
 * `userData.pick`: у каждой призмы свой диапазон треугольников, клик находит элемент бинарным
 * поиском по номеру грани. Отдельных мешей на конструкцию нет - размер модели на скорость не влияет.
 */

/** Цвета категорий: значения CSS-токенов темы, не хардкод. */
export interface IFloor3dColors {
  readonly slab: string;
  readonly masonry: string;
  readonly monolith: string;
  readonly framePartition: string;
  readonly lintel: string;
  readonly door: string;
  readonly candidate: string;
  readonly enabled: string;
  readonly edge: string;
  /** Выделение выбранного элемента и маркеры измерения. */
  readonly accent: string;
  /** Контур отверстия в состоянии «Не отверстие». */
  readonly muted: string;
}

const FALLBACK_COLOR = 'gray';

/** Полотно двери слегка прозрачно: за ним видна планировка. */
const DOOR_OPACITY = 0.8;

export const readFloor3dColors = (): IFloor3dColors => {
  if (typeof document === 'undefined') {
    return {
      slab: FALLBACK_COLOR,
      masonry: FALLBACK_COLOR,
      monolith: FALLBACK_COLOR,
      framePartition: FALLBACK_COLOR,
      lintel: FALLBACK_COLOR,
      door: FALLBACK_COLOR,
      candidate: FALLBACK_COLOR,
      enabled: FALLBACK_COLOR,
      edge: FALLBACK_COLOR,
      accent: FALLBACK_COLOR,
      muted: FALLBACK_COLOR,
    };
  }
  const style = getComputedStyle(document.documentElement);
  const token = (name: string): string => style.getPropertyValue(name).trim() || FALLBACK_COLOR;
  return {
    slab: token('--border-strong'),
    masonry: token('--cad-construction-masonry'),
    monolith: token('--cad-construction-monolith'),
    // Как в 2D (constructions-painter): перегородка красится цветом кладки, отличается штрихом.
    framePartition: token('--cad-construction-masonry'),
    lintel: token('--cad-construction-check'),
    door: token('--cad-layer-6'),
    candidate: token('--danger'),
    enabled: token('--success'),
    edge: token('--text'),
    accent: token('--accent'),
    muted: token('--muted'),
  };
};

/** Что лежит под мешем: элементы в порядке слияния и диапазоны их треугольников. */
export interface IFloor3dPickData {
  readonly kind: 'prism' | 'hole';
  readonly category: PrismCategory | 'hole';
  readonly ids: readonly string[];
  /** Номер первого треугольника каждого элемента. */
  readonly starts: readonly number[];
  readonly total: number;
}

export interface IFloor3dScene {
  readonly group: THREE.Group;
  /** Меши, по которым работает клик. */
  readonly pickables: readonly THREE.Mesh[];
  readonly slabCap: THREE.Object3D | null;
  /** Оверлей выделения поверх слитой геометрии; пусто - снять. Прежний освобождается. */
  setHighlight: (targets: readonly IFloor3dHighlight[]) => void;
  /** Показать или скрыть категорию (Object3D.visible, без пересборки). Скрытое в клик не входит. */
  setCategoryVisible: (category: CadLayerCategory, visible: boolean) => void;
  /**
   * Скрыть конструкции по id (Object3D.visible, без пересборки): подгруппа скрывается, когда скрыты
   * все её id. Работает для кладки, монолита и каркасных перегородок; пусто - показать всё.
   */
  setHiddenIds: (ids: ReadonlySet<string>) => void;
  dispose: () => void;
}

export interface IFloor3dPick {
  readonly kind: 'prism' | 'hole';
  readonly category: PrismCategory | 'hole';
  readonly id: string;
}

const toVector = (points: readonly Point2[]): THREE.Vector2[] =>
  points.map(([u, v]) => new THREE.Vector2(u, v));

/** Контур в плане (u, v) лежит в плоскости XY; поворот на -90° вокруг X даёт (u, высота, -v). */
const shapeOf = (shell: readonly Point2[], holes: readonly (readonly Point2[])[]): THREE.Shape => {
  const shape = new THREE.Shape(toVector(shell));
  shape.holes = holes.map((hole) => new THREE.Path(toVector(hole)));
  return shape;
};

const prismGeometry = (spec: IPrismSpec): THREE.BufferGeometry | null => {
  const depth = spec.yTop - spec.yBottom;
  if (!(depth > 0)) return null;
  try {
    const geometry = new THREE.ExtrudeGeometry(shapeOf(spec.shell, spec.holes), {
      depth,
      bevelEnabled: false,
      steps: 1,
    });
    geometry.rotateX(-Math.PI / 2);
    geometry.translate(0, spec.yBottom, 0);
    return geometry.getAttribute('position').count > 0 ? geometry : null;
  } catch {
    // Самопересекающийся контур триангуляция не берёт: элемент пропускается, вид строится дальше.
    return null;
  }
};

const holeGeometry = (spec: IHoleSpec, lift: number): THREE.BufferGeometry | null => {
  try {
    const geometry = new THREE.ShapeGeometry(shapeOf(spec.contour, []));
    geometry.rotateX(-Math.PI / 2);
    geometry.translate(0, spec.y + lift, 0);
    return geometry.getAttribute('position').count > 0 ? geometry : null;
  } catch {
    return null;
  }
};

/** Треугольников в геометрии: у индексированной (ShapeGeometry) - по индексу, у остальных - по вершинам. */
const triangleCount = (geometry: THREE.BufferGeometry): number =>
  (geometry.index?.count ?? geometry.getAttribute('position').count) / 3;

interface IMerged {
  readonly geometry: THREE.BufferGeometry;
  readonly pick: IFloor3dPickData;
}

/** Слияние с картой «треугольник -> элемент»; элементы без геометрии пропускаются. */
const mergeItems = (
  items: readonly { id: string; geometry: THREE.BufferGeometry | null }[],
  kind: IFloor3dPickData['kind'],
  category: IFloor3dPickData['category'],
): IMerged | null => {
  const built = items.filter(
    (item): item is { id: string; geometry: THREE.BufferGeometry } => item.geometry !== null,
  );
  if (built.length === 0) return null;
  const starts: number[] = [];
  let total = 0;
  for (const item of built) {
    starts.push(total);
    total += triangleCount(item.geometry);
  }
  const geometry = mergeGeometries(built.map((item) => item.geometry), false);
  for (const item of built) item.geometry.dispose();
  if (geometry === null) return null;
  return { geometry, pick: { kind, category, ids: built.map((item) => item.id), starts, total } };
};

/** Категории, чьи слитые меши делятся на подгруппы по набору слоёв-источников. */
const SPLIT_CATEGORIES: ReadonlySet<PrismCategory> = new Set<PrismCategory>([
  'masonry',
  'monolith',
  'frame_partition',
]);

export const buildFloor3dScene = (
  plan: IFloor3dPlan,
  colors: IFloor3dColors,
  options: {
    readonly showSlabCap: boolean;
    /**
     * Ключ подгруппы конструкции: у конструкций одной подгруппы одинаковый набор слоёв-источников,
     * поэтому видимость подгруппы однозначна. Нет функции или ключа - общая группа категории.
     */
    readonly groupKeyOf?: (id: string) => string | undefined;
    /**
     * Категория слоя стены-хозяина по её id: перемычки скрываются вместе со стеной. Нет функции или
     * хозяин не найден - перемычка следует «Монолит - стены и пилоны» (монолит) или «Кладке».
     */
    readonly hostCategoryOf?: HostCategoryOf;
  },
): IFloor3dScene => {
  const group = new THREE.Group();
  const pickables: THREE.Mesh[] = [];
  const disposables: { dispose: () => void }[] = [];

  const track = <T extends { dispose: () => void }>(item: T): T => {
    disposables.push(item);
    return item;
  };

  // Объекты по категориям видимости: меши, рёбра, отверстия и копия плиты сверху.
  // Видимость объекта = категория не скрыта и подгруппа (если есть) не скрыта по id.
  interface IRegistered {
    readonly category: CadLayerCategory;
    readonly object: THREE.Object3D;
    /** id подгруппы; `null` - объект управляется только категорией. */
    readonly ids: readonly string[] | null;
  }
  const registered: IRegistered[] = [];
  const hiddenCategorySet = new Set<CadLayerCategory>();
  let hiddenIdSet: ReadonlySet<string> = new Set<string>();
  const applyVisibility = (item: IRegistered): void => {
    const byIds =
      item.ids !== null && item.ids.length > 0 && item.ids.every((id) => hiddenIdSet.has(id));
    item.object.visible = !hiddenCategorySet.has(item.category) && !byIds;
  };
  const register = (
    category: CadLayerCategory,
    object: THREE.Object3D,
    ids: readonly string[] | null = null,
  ): void => {
    registered.push({ category, object, ids });
  };

  const solid = (color: string, opacity = 1) =>
    track(
      new THREE.MeshLambertMaterial({
        color: new THREE.Color(color),
        ...(opacity < 1 ? { transparent: true, opacity } : {}),
      }),
    );
  const edgeMaterial = track(
    new THREE.LineBasicMaterial({ color: new THREE.Color(colors.edge), transparent: true, opacity: 0.35 }),
  );

  // Перемычки красятся по материалу: монолит - цветом монолита, кладка и каркасная перегородка -
  // цветом кладки, материал не определён - цветом перемычки. Категория видимости - стены-хозяина (см. `visibilityOf`).
  const isUndefinedMaterial = (item: IPrismSpec): boolean =>
    item.material !== 'monolith' && item.material !== 'masonry' && item.material !== 'frame_partition';
  const groups: readonly {
    category: PrismCategory;
    color: string;
    include: (item: IPrismSpec) => boolean;
  }[] = [
    { category: 'slab', color: colors.slab, include: () => true },
    { category: 'masonry', color: colors.masonry, include: () => true },
    { category: 'monolith', color: colors.monolith, include: () => true },
    { category: 'frame_partition', color: colors.framePartition, include: () => true },
    { category: 'lintel', color: colors.lintel, include: isUndefinedMaterial },
    { category: 'lintel', color: colors.monolith, include: (item) => item.material === 'monolith' },
    {
      category: 'lintel',
      color: colors.masonry,
      include: (item) => item.material === 'masonry' || item.material === 'frame_partition',
    },
    { category: 'door', color: colors.door, include: () => true },
  ];
  const groupKeyOf = options.groupKeyOf;
  const hostCategoryOf = options.hostCategoryOf;
  for (const { category, color, include } of groups) {
    const items = plan.prisms.filter((item) => item.category === category && include(item));
    // Кладка, монолит и перегородки делятся на подгруппы по слоям-источникам: слой скрывается без
    // пересборки. Перемычки делятся по категории и слоям стены-хозяина: прячутся вместе с ней.
    // Прочие категории - один меш, как раньше.
    interface ISubgroup {
      readonly visibility: CadLayerCategory;
      /** Скрывается и по id конструкций (у перемычек - id хозяев); иначе только категорией. */
      readonly byIds: boolean;
      readonly members: IPrismSpec[];
    }
    const subgroups = new Map<string, ISubgroup>();
    for (const item of items) {
      const visibility = visibilityOf(item, hostCategoryOf);
      const hostId = item.hostId ?? null;
      const lintelKey =
        category === 'lintel' && hostId !== null && hostCategoryOf?.(hostId) !== undefined
          ? (groupKeyOf?.(hostId) ?? '')
          : '';
      const key = SPLIT_CATEGORIES.has(category) ? (groupKeyOf?.(item.id) ?? '') : lintelKey;
      const id = `${visibility}\u0005${key}`;
      const found = subgroups.get(id);
      if (found !== undefined) found.members.push(item);
      else subgroups.set(id, { visibility, byIds: key !== '', members: [item] });
    }
    for (const sub of subgroups.values()) {
      const merged = mergeItems(
        sub.members.map((item) => ({ id: item.id, geometry: prismGeometry(item) })),
        'prism',
        category,
      );
      if (merged === null) continue;
      track(merged.geometry);
      const ids =
        !sub.byIds
          ? null
          : category === 'lintel'
            ? [...new Set(sub.members.flatMap((item) => (item.hostId == null ? [] : [item.hostId])))]
            : merged.pick.ids;
      const mesh = new THREE.Mesh(merged.geometry, solid(color, category === 'door' ? DOOR_OPACITY : 1));
      mesh.userData.pick = merged.pick;
      group.add(mesh);
      pickables.push(mesh);
      register(sub.visibility, mesh, ids);
      const edges = new THREE.EdgesGeometry(merged.geometry, 30);
      track(edges);
      const edgeLines = new THREE.LineSegments(edges, edgeMaterial);
      group.add(edgeLines);
      register(sub.visibility, edgeLines, ids);
    }
  }

  // Отверстия плиты: кандидат - полупрозрачная заливка и контур, включённое - контур, «Не отверстие» -
  // тонкий нейтральный контур на сплошной плите. Для клика по включённому и выключенному отверстию
  // кладётся невидимый плоский меш (material.visible = false): не рисуется, но луч его находит, а
  // контур тонкой линии луч ловил бы ненадёжно (порог Line зависит от масштаба). Меш лежит на 3 мм
  // выше плиты, поэтому ближе к камере и перехватывает клик у плиты.
  const lift = 0.003;
  const candidates = plan.holes.filter((hole) => hole.state === 'candidate');
  const decided = [...plan.holes.filter((hole) => hole.state === 'enabled'), ...plan.disabledHoles];
  const fill = mergeItems(
    candidates.map((hole) => ({ id: hole.key, geometry: holeGeometry(hole, lift) })),
    'hole',
    'hole',
  );
  if (fill !== null) {
    track(fill.geometry);
    const material = track(
      new THREE.MeshBasicMaterial({
        color: new THREE.Color(colors.candidate),
        transparent: true,
        opacity: 0.45,
        side: THREE.DoubleSide,
        depthWrite: false,
      }),
    );
    const mesh = new THREE.Mesh(fill.geometry, material);
    mesh.userData.pick = fill.pick;
    group.add(mesh);
    pickables.push(mesh);
    register('slab', mesh);
  }
  const hidden = mergeItems(
    decided.map((hole) => ({ id: hole.key, geometry: holeGeometry(hole, lift) })),
    'hole',
    'hole',
  );
  if (hidden !== null) {
    track(hidden.geometry);
    const material = track(new THREE.MeshBasicMaterial({ side: THREE.DoubleSide }));
    material.visible = false;
    const mesh = new THREE.Mesh(hidden.geometry, material);
    mesh.userData.pick = hidden.pick;
    group.add(mesh);
    pickables.push(mesh);
    register('slab', mesh);
  }
  const outline = (hole: IHoleSpec, color: string): void => {
    const points = hole.contour.map(([u, v]) => new THREE.Vector3(u, hole.y + lift, -v));
    const geometry = track(new THREE.BufferGeometry().setFromPoints(points));
    const loop = new THREE.LineLoop(geometry, track(new THREE.LineBasicMaterial({ color: new THREE.Color(color) })));
    group.add(loop);
    register('slab', loop);
  };
  for (const hole of plan.holes) outline(hole, hole.state === 'candidate' ? colors.candidate : colors.enabled);
  for (const hole of plan.disabledHoles) outline(hole, colors.muted);

  // «Плита сверху»: полупрозрачная копия плиты на верхе стен, в клик не входит.
  let slabCap: THREE.Object3D | null = null;
  if (options.showSlabCap && plan.slabCap !== null) {
    const geometry = prismGeometry(plan.slabCap);
    if (geometry !== null) {
      track(geometry);
      const material = track(
        new THREE.MeshLambertMaterial({
          color: new THREE.Color(colors.slab),
          transparent: true,
          opacity: 0.35,
          depthWrite: false,
        }),
      );
      slabCap = new THREE.Mesh(geometry, material);
      group.add(slabCap);
      register('slab', slabCap);
    }
  }

  // Выделение: отдельный оверлей, в клик не входит. Заливка акцентом с прозрачностью и контур рёбер;
  // polygonOffset убирает мерцание на совпадающих гранях, контур рисуется поверх (depthTest выключен).
  let overlay: THREE.Group | null = null;
  const overlayDisposables: { dispose: () => void }[] = [];
  const clearOverlay = (): void => {
    if (overlay !== null) group.remove(overlay);
    overlay = null;
    for (const item of overlayDisposables.splice(0)) item.dispose();
  };
  const own = <T extends { dispose: () => void }>(item: T): T => {
    overlayDisposables.push(item);
    return item;
  };
  const setHighlight = (targets: readonly IFloor3dHighlight[]): void => {
    clearOverlay();
    if (targets.length === 0) return;
    const accent = new THREE.Color(colors.accent);
    const next = new THREE.Group();
    const lineMaterial = own(new THREE.LineBasicMaterial({ color: accent, depthTest: false }));

    // Призмы (стены, плита, перемычка, дверь) сливаются в одну геометрию: группа из сотен стен -
    // два объекта оверлея, а не сотни.
    const prisms = targets
      .flatMap((target) => (target.kind === 'prism' ? [prismGeometry(target.spec)] : []))
      .filter((geometry): geometry is THREE.BufferGeometry => geometry !== null);
    if (prisms.length > 0) {
      const merged = prisms.length === 1 ? prisms[0] : mergeGeometries(prisms, false);
      if (prisms.length > 1) for (const item of prisms) item.dispose();
      if (merged !== null && merged !== undefined) {
        own(merged);
        const fillMaterial = own(
          new THREE.MeshBasicMaterial({
            color: accent,
            transparent: true,
            opacity: 0.45,
            depthWrite: false,
            polygonOffset: true,
            polygonOffsetFactor: -2,
            polygonOffsetUnits: -2,
          }),
        );
        next.add(new THREE.Mesh(merged, fillMaterial));
        const edges = own(new THREE.EdgesGeometry(merged, 30));
        const lines = new THREE.LineSegments(edges, lineMaterial);
        lines.renderOrder = 10;
        next.add(lines);
      }
    }

    for (const target of targets) {
      if (target.kind !== 'hole') continue;
      const spec = target.spec;
      const geometry = holeGeometry(spec, lift * 2);
      if (geometry !== null) {
        own(geometry);
        next.add(
          new THREE.Mesh(
            geometry,
            own(
              new THREE.MeshBasicMaterial({
                color: accent,
                transparent: true,
                opacity: 0.35,
                side: THREE.DoubleSide,
                depthWrite: false,
              }),
            ),
          ),
        );
      }
      const points = spec.contour.map(([u, v]) => new THREE.Vector3(u, spec.y + lift * 2, -v));
      const loop = new THREE.LineLoop(own(new THREE.BufferGeometry().setFromPoints(points)), lineMaterial);
      loop.renderOrder = 10;
      next.add(loop);
    }
    if (next.children.length === 0) return;
    overlay = next;
    group.add(next);
  };

  const setCategoryVisible = (category: CadLayerCategory, visible: boolean): void => {
    if (visible) hiddenCategorySet.delete(category);
    else hiddenCategorySet.add(category);
    for (const item of registered) if (item.category === category) applyVisibility(item);
  };

  const setHiddenIds = (ids: ReadonlySet<string>): void => {
    hiddenIdSet = ids;
    for (const item of registered) if (item.ids !== null) applyVisibility(item);
  };

  return {
    group,
    pickables,
    slabCap,
    setHighlight,
    setCategoryVisible,
    setHiddenIds,
    dispose: () => {
      clearOverlay();
      for (const item of disposables) item.dispose();
      group.clear();
    },
  };
};

/** Элемент под гранью, в которую попал луч; `null` - меш не наш или грань вне карты. */
export const pickOf = (mesh: THREE.Object3D, faceIndex: number | undefined | null): IFloor3dPick | null => {
  const data = mesh.userData.pick as IFloor3dPickData | undefined;
  if (data === undefined || faceIndex === undefined || faceIndex === null) return null;
  const index = itemAtTriangle(data.starts, data.total, faceIndex);
  const id = index < 0 ? undefined : data.ids[index];
  return id === undefined ? null : { kind: data.kind, category: data.category, id };
};
