'use client';

import { useMemo, useState } from 'react';

import {
  EXTRA_CATEGORIES,
  hiddenCategoriesOf,
  type CadExtraCategory,
  type CadLayerCategory,
} from '@/lib/cad/layer-categories';

/**
 * Ключ браузерного хранилища скрытых слоёв листа: ревизия документа и страница, не задание, -
 * новое преобразование того же листа не сбрасывает выбор (хранятся имена слоёв).
 */
export const layerVisibilityKey = (revisionId: string, pageIndex: number): string =>
  `quantor.cad.layers-hidden.v2:${revisionId}:${pageIndex}`;

/** Прежний ключ v1 (по заданию): читается один раз для переноса в v2, не пишется. */
export const legacyLayerVisibilityKey = (jobId: string, pageIndex: number): string =>
  `quantor.cad.layers-hidden.v1:${jobId}:${pageIndex}`;

interface IStored {
  /** Имена скрытых слоёв DXF (не индексы: индексы зависят от вида). */
  readonly layers: readonly string[];
  /** Скрытые строки без слоя DXF: «Плита» и «Перемычки». */
  readonly extra: readonly CadExtraCategory[];
}

const EMPTY: IStored = { layers: [], extra: [] };

/** Разбор записи; `null` - записи нет. Битый JSON и чужой формат - ничего не скрыто. */
const parseStored = (raw: string | null): IStored | null => {
  if (raw === null) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return EMPTY;
    const { layers, extra } = parsed as { layers?: unknown; extra?: unknown };
    return {
      layers: Array.isArray(layers)
        ? layers.filter((item): item is string => typeof item === 'string')
        : [],
      extra: Array.isArray(extra)
        ? EXTRA_CATEGORIES.filter((category) => extra.includes(category))
        : [],
    };
  } catch {
    return EMPTY;
  }
};

/**
 * Чтение с защитой: хранилища нет, JSON битый или формат чужой - ничего не скрыто. Записи v2 нет,
 * а есть `legacyKey` (v1 по заданию) - берётся она и разово переписывается в v2.
 */
export const readLayerVisibility = (key: string | null, legacyKey: string | null = null): IStored => {
  if (key === null) return EMPTY;
  try {
    const current = parseStored(window.localStorage.getItem(key));
    if (current !== null) return current;
    if (legacyKey === null) return EMPTY;
    const legacy = parseStored(window.localStorage.getItem(legacyKey));
    if (legacy === null) return EMPTY;
    writeLayerVisibility(key, legacy);
    return legacy;
  } catch {
    return EMPTY;
  }
};

/** Запись; хранилище недоступно - выбор живёт до перезагрузки. */
export const writeLayerVisibility = (key: string | null, value: IStored): void => {
  if (key === null) return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // хранилище недоступно (приватный режим, квота) - выбор остаётся в состоянии
  }
};

export interface ICadLayerVisibility {
  /** Индексы скрытых слоёв DXF в текущем `layerNames`. */
  readonly hiddenLayers: ReadonlySet<number>;
  /** Скрытые категории конструкций: из слоёв DXF и строки «Плита»/«Перемычки». */
  readonly hiddenCategories: ReadonlySet<CadLayerCategory>;
  /** Имена скрытых слоёв DXF: по ним скрываются конструкции с этими слоями-источниками. */
  readonly hiddenLayerNames: ReadonlySet<string>;
  readonly toggleLayer: (index: number) => void;
  readonly setLayersHidden: (indices: readonly number[], hidden: boolean) => void;
  readonly setExtraHidden: (category: CadExtraCategory, hidden: boolean) => void;
  /** Строки «Плита» и «Перемычки» вкладки «Слои»: показаны ли и как переключить. */
  readonly categories: {
    readonly slab: boolean;
    readonly lintel: boolean;
    readonly onChange: (category: CadExtraCategory, visible: boolean) => void;
  };
}

/**
 * Видимость слоёв листа - один источник правды для плана и 3D. Скрытые слои хранятся по именам,
 * не сбрасываются при смене вида и режима «план/3D» и переживают перезагрузку (localStorage по
 * листу и странице). `legacyKey` - ключ v1 по заданию для разового переноса. `storageKey = null` - вида нет, ничего не скрыто и не пишется.
 */
export const useCadLayerVisibility = (
  storageKey: string | null,
  layerNames: readonly string[],
  legacyKey: string | null = null,
): ICadLayerVisibility => {
  const [state, setState] = useState<{ key: string | null; value: IStored }>(() => ({
    key: storageKey,
    value: readLayerVisibility(storageKey, legacyKey),
  }));
  // Лист другой - читаем его выбор из хранилища.
  let current = state.value;
  if (state.key !== storageKey) {
    current = readLayerVisibility(storageKey, legacyKey);
    setState({ key: storageKey, value: current });
  }

  const commit = (next: IStored) => {
    setState({ key: storageKey, value: next });
    writeLayerVisibility(storageKey, next);
  };

  const hiddenNames = useMemo(() => new Set(current.layers), [current.layers]);
  const hiddenExtra = useMemo(() => new Set(current.extra), [current.extra]);

  const hiddenLayers = useMemo<ReadonlySet<number>>(
    () =>
      new Set(
        layerNames.flatMap((name, index) => (hiddenNames.has(name) ? [index] : [])),
      ),
    [layerNames, hiddenNames],
  );
  const hiddenCategories = useMemo(
    () => hiddenCategoriesOf(layerNames, hiddenNames, hiddenExtra),
    [layerNames, hiddenNames, hiddenExtra],
  );

  const setLayersHidden = (indices: readonly number[], hidden: boolean) => {
    const names = new Set(current.layers);
    for (const index of indices) {
      const name = layerNames[index];
      if (name === undefined) continue;
      if (hidden) names.add(name);
      else names.delete(name);
    }
    commit({ layers: [...names], extra: current.extra });
  };

  const setExtraHidden = (category: CadExtraCategory, hidden: boolean) => {
    const extra = new Set(current.extra);
    if (hidden) extra.add(category);
    else extra.delete(category);
    commit({ layers: current.layers, extra: [...extra] });
  };

  return {
    hiddenLayers,
    hiddenCategories,
    hiddenLayerNames: hiddenNames,
    toggleLayer: (index) => setLayersHidden([index], !hiddenLayers.has(index)),
    setLayersHidden,
    setExtraHidden,
    categories: {
      slab: !hiddenExtra.has('slab'),
      lintel: !hiddenExtra.has('lintel'),
      onChange: (category, visible) => setExtraHidden(category, !visible),
    },
  };
};
