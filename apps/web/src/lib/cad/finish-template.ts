import type {
  CadFinishLayer,
  CadFinishTemplatePatch,
  CadFinishTemplateRead,
  CadFinishTemplateWrite,
} from '@quantor/api-client';

import { FINISH_BASES, type FinishBase, type FinishSurface, type RoomType } from './room-types';

/**
 * Черновик шаблона отделки для формы: поля - текст, как их вводит человек. Преобразование в
 * тело запроса и проверка границ повторяют контракт сервера (`cad_finishes`); сервер всё равно
 * проверяет заново. Чистая логика без DOM и сети.
 */

export const MAX_LAYERS = 20;
export const MAX_COATS = 5;
export const THICKNESS_MAX_MM = 200;
export const WALL_HEIGHT_MIN_MM = 1000;
export const WALL_HEIGHT_MAX_MM = 6000;
export const TEXT_MAX = 200;
export const UNIT_MAX = 20;

export interface IFinishLayerDraft {
  /** Стабильный ключ строки для React; на сервер не уходит. */
  readonly key: string;
  readonly work: string;
  readonly material: string;
  readonly coats: string;
  readonly thickness: string;
  readonly consumption: string;
  readonly unit: string;
  readonly perMm: boolean;
  /** Основания слоя стен; пусто - все основания (`null` в теле). Для пола и потолка не используется. */
  readonly bases: readonly FinishBase[];
}

/** Слои трёх поверхностей названы так же, как коды поверхностей ведомости: `draft[surface]`. */
export interface ITemplateDraft {
  readonly name: string;
  readonly roomTypes: readonly RoomType[];
  readonly wallHeight: string;
  /** Откосы дверных проёмов входят в слои стен. */
  readonly wallsIncludeReveals: boolean;
  readonly floor: readonly IFinishLayerDraft[];
  readonly walls: readonly IFinishLayerDraft[];
  readonly ceiling: readonly IFinishLayerDraft[];
}

let keyCounter = 0;
const nextKey = (): string => {
  keyCounter += 1;
  return `layer-${keyCounter}`;
};

export const emptyLayer = (
  work = '',
  coats = 1,
  bases: readonly FinishBase[] = [],
): IFinishLayerDraft => ({
  key: nextKey(),
  work,
  material: '',
  coats: String(coats),
  thickness: '',
  consumption: '',
  unit: '',
  perMm: false,
  bases,
});

export const emptyDraft = (): ITemplateDraft => ({
  name: '',
  roomTypes: [],
  wallHeight: '',
  wallsIncludeReveals: false,
  floor: [],
  walls: [],
  ceiling: [],
});

// --- заготовки: только работы и число слоёв, числа расхода и толщин задаёт человек ---

type PresetStep = readonly [work: string, coats: number, bases?: readonly FinishBase[]];

interface IPreset {
  readonly id: string;
  readonly title: string;
  readonly floor: readonly PresetStep[];
  readonly walls: readonly PresetStep[];
  readonly ceiling: readonly PresetStep[];
}

export const FINISH_PRESETS: readonly IPreset[] = [
  {
    id: 'mop-rough',
    title: 'Черновая МОП',
    floor: [
      ['Обеспыливание', 1],
      ['Грунтовка', 1],
      ['Стяжка', 1],
    ],
    walls: [
      ['Обеспыливание', 1, ['monolith']],
      ['Грунтовка', 1],
      ['Штукатурка', 1, ['monolith', 'masonry']],
      ['Шпаклёвка', 1],
      ['Окраска', 2],
    ],
    ceiling: [
      ['Обеспыливание', 1],
      ['Грунтовка', 1],
      ['Шпаклёвка', 1],
      ['Окраска', 2],
    ],
  },
  {
    id: 'apartment-rough',
    title: 'Черновая квартира',
    floor: [
      ['Грунтовка', 1],
      ['Стяжка', 1],
    ],
    walls: [
      ['Грунтовка', 1],
      ['Штукатурка', 1, ['monolith', 'masonry']],
    ],
    ceiling: [
      ['Обеспыливание', 1],
      ['Грунтовка', 1],
    ],
  },
];

const layersOf = (steps: readonly PresetStep[]): IFinishLayerDraft[] =>
  steps.map(([work, coats, bases]) => emptyLayer(work, coats, bases));

/**
 * Подставляет заготовку: заменяет слои трёх поверхностей; название, типы помещений, высоту и
 * флажок откосов не трогает.
 */
export const applyPreset = (draft: ITemplateDraft, presetId: string): ITemplateDraft => {
  const preset = FINISH_PRESETS.find((item) => item.id === presetId);
  if (preset === undefined) return draft;
  return {
    ...draft,
    floor: layersOf(preset.floor),
    walls: layersOf(preset.walls),
    ceiling: layersOf(preset.ceiling),
  };
};

// --- сервер <-> черновик ---

const numText = (value: number | null | undefined): string =>
  value === null || value === undefined ? '' : String(value).replace('.', ',');

/** Основания в каноническом порядке без повторов; для пола и потолка - пусто. */
const sortedBases = (bases: readonly FinishBase[] | null | undefined): FinishBase[] =>
  FINISH_BASES.filter((base) => bases?.includes(base) === true);

const layerDraft = (layer: CadFinishLayer): IFinishLayerDraft => ({
  key: nextKey(),
  work: layer.work,
  material: layer.material ?? '',
  coats: String(layer.coats ?? 1),
  thickness: numText(layer.thickness_mm),
  consumption: numText(layer.consumption),
  unit: layer.consumption_unit ?? '',
  perMm: layer.consumption_per_mm ?? false,
  bases: sortedBases(layer.bases),
});

export const draftFromTemplate = (template: CadFinishTemplateRead): ITemplateDraft => ({
  name: template.name,
  roomTypes: template.room_types,
  wallHeight: template.wall_height_mm === null ? '' : String(template.wall_height_mm),
  wallsIncludeReveals: template.walls_include_reveals,
  floor: template.floor_layers.map(layerDraft),
  walls: template.wall_layers.map(layerDraft),
  ceiling: template.ceiling_layers.map(layerDraft),
});

// --- проверка и сборка тела ---

/** Число из поля: пустое - `null`; запятая допустима; не число - `NaN`. */
export const parseDecimal = (raw: string): number | null => {
  const text = raw.trim().replace(',', '.');
  if (text === '') return null;
  return /^\d+(\.\d+)?$/.test(text) ? Number(text) : Number.NaN;
};

export interface ILayerProblems {
  work?: string;
  coats?: string;
  thickness?: string;
  consumption?: string;
  unit?: string;
}

export const layerProblems = (layer: IFinishLayerDraft): ILayerProblems => {
  const problems: ILayerProblems = {};
  if (layer.work.trim() === '') problems.work = 'Укажите работу';
  const coats = parseDecimal(layer.coats);
  if (
    coats === null ||
    Number.isNaN(coats) ||
    !Number.isInteger(coats) ||
    coats < 1 ||
    coats > MAX_COATS
  ) {
    problems.coats = `Раз: целое от 1 до ${MAX_COATS}`;
  }
  const thickness = parseDecimal(layer.thickness);
  if (
    Number.isNaN(thickness) ||
    (thickness !== null && (thickness <= 0 || thickness > THICKNESS_MAX_MM))
  ) {
    problems.thickness = `Толщина: больше 0 и не более ${THICKNESS_MAX_MM} мм`;
  }
  const consumption = parseDecimal(layer.consumption);
  if (Number.isNaN(consumption) || (consumption !== null && consumption <= 0)) {
    problems.consumption = 'Расход: число больше 0';
  } else if (consumption !== null && layer.unit.trim() === '') {
    problems.unit = 'Укажите единицу расхода';
  }
  if (layer.perMm && thickness === null && problems.thickness === undefined) {
    problems.thickness = 'Расход на мм требует толщину слоя';
  }
  return problems;
};

export const hasLayerProblems = (problems: ILayerProblems): boolean =>
  Object.keys(problems).length > 0;

export interface ITemplateProblems {
  name?: string;
  wallHeight?: string;
}

export const templateProblems = (draft: ITemplateDraft): ITemplateProblems => {
  const problems: ITemplateProblems = {};
  if (draft.name.trim() === '') problems.name = 'Укажите название шаблона';
  const height = parseDecimal(draft.wallHeight);
  if (
    Number.isNaN(height) ||
    (height !== null &&
      (!Number.isInteger(height) || height < WALL_HEIGHT_MIN_MM || height > WALL_HEIGHT_MAX_MM))
  ) {
    problems.wallHeight = `Высота: целое от ${WALL_HEIGHT_MIN_MM} до ${WALL_HEIGHT_MAX_MM} мм`;
  }
  return problems;
};

/** Все поверхности черновика одним списком: для проверки и сборки. */
const allLayers = (draft: ITemplateDraft): readonly IFinishLayerDraft[] => [
  ...draft.floor,
  ...draft.walls,
  ...draft.ceiling,
];

/** Черновик можно отправлять: нет проблем в шаблоне и ни в одном слое. */
export const isDraftValid = (draft: ITemplateDraft): boolean =>
  !Object.keys(templateProblems(draft)).length &&
  allLayers(draft).every((layer) => !hasLayerProblems(layerProblems(layer)));

/** Основания тела слоя стен: ни одного или все три - `null` («все основания»). */
const basesBody = (bases: readonly FinishBase[]): FinishBase[] | null => {
  const picked = sortedBases(bases);
  return picked.length === 0 || picked.length === FINISH_BASES.length ? null : picked;
};

const layerBody = (layer: IFinishLayerDraft, surface: FinishSurface): CadFinishLayer => ({
  work: layer.work.trim(),
  material: layer.material.trim() === '' ? null : layer.material.trim(),
  coats: parseDecimal(layer.coats) ?? 1,
  thickness_mm: parseDecimal(layer.thickness),
  consumption: parseDecimal(layer.consumption),
  consumption_unit: layer.unit.trim() === '' ? null : layer.unit.trim(),
  consumption_per_mm: layer.perMm,
  // основания есть только у слоёв стен
  ...(surface === 'walls' ? { bases: basesBody(layer.bases) } : {}),
});

/** Тело создания шаблона. Вызывать для проверенного черновика. */
export const toWriteBody = (draft: ITemplateDraft): CadFinishTemplateWrite => ({
  name: draft.name.trim(),
  room_types: [...draft.roomTypes],
  wall_height_mm: parseDecimal(draft.wallHeight),
  walls_include_reveals: draft.wallsIncludeReveals,
  floor_layers: draft.floor.map((layer) => layerBody(layer, 'floor')),
  wall_layers: draft.walls.map((layer) => layerBody(layer, 'walls')),
  ceiling_layers: draft.ceiling.map((layer) => layerBody(layer, 'ceiling')),
});

/** Тело правки: передаются все поля, пустая высота (`null`) очищает хранимую. */
export const toPatchBody = (draft: ITemplateDraft): CadFinishTemplatePatch => toWriteBody(draft);
