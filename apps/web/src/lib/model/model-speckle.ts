import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

import type { IModelElement } from './model-elements';
import type { IModelPartInput } from './model-scene';

/**
 * Просмотрщик Speckle (`@speckle/viewer`, Apache-2.0) для модели здания (ADR-0053).
 *
 * Сервер Speckle не нужен: части GLB пакета QMP разбираются в браузере, переводятся в объекты
 * Speckle (корень со ссылками на элементы, элемент со свойствами и ссылкой на сетку) и отдаются
 * просмотрщику из памяти. Геометрия в метрах; оси glTF (Y вверх) переводятся в оси Speckle
 * (Z вверх) поворотом без отражения. Тяжёлая библиотека подгружается только при открытии 3D.
 */

const COORD_DECIMALS = 10_000;
const FIT_TRANSITION = true;
/** Группа свойств элемента: так её показывают фильтры и панель свойств просмотрщика. */
const PROPS_GROUP = 'Параметры IFC';

export interface ISpeckleObject {
  id: string;
  speckle_type: string;
  __closure?: Record<string, number>;
  [key: string]: unknown;
}

export interface ISpeckleResource {
  /** Идентификатор ресурса просмотрщика: по нему часть выгружается. */
  readonly resource: string;
  readonly discipline: string;
  /** Корень первым, дальше элементы и их сетки. */
  readonly objects: readonly ISpeckleObject[];
  /** id элемента пакета (GlobalId) -> id объекта Speckle. */
  readonly speckleIds: ReadonlyMap<string, string>;
}

/** Идентификатор объекта Speckle: часть + элемент, чтобы одинаковые id разных частей не слились. */
export const speckleIdOf = (partKey: string, elementId: string): string =>
  `${partKey}:${elementId}`;

const round = (value: number): number => Math.round(value * COORD_DECIMALS) / COORD_DECIMALS;

interface IMeshData {
  readonly vertices: number[];
  readonly faces: number[];
}

/** Все меши узла в одну сетку Speckle: вершины в мировых осях узла, треугольники по три индекса. */
const meshOf = (node: THREE.Object3D): IMeshData | null => {
  const vertices: number[] = [];
  const faces: number[] = [];
  node.updateWorldMatrix(true, true);
  const point = new THREE.Vector3();
  node.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    const geometry = object.geometry as THREE.BufferGeometry;
    const position = geometry.getAttribute('position');
    if (position === undefined) return;
    const offset = vertices.length / 3;
    for (let index = 0; index < position.count; index += 1) {
      point.fromBufferAttribute(position, index).applyMatrix4(object.matrixWorld);
      vertices.push(round(point.x), round(-point.z), round(point.y));
    }
    const indices = geometry.getIndex();
    const count = indices === null ? position.count : indices.count;
    const at = (slot: number): number => offset + (indices === null ? slot : indices.getX(slot));
    for (let slot = 0; slot + 2 < count; slot += 3) {
      faces.push(3, at(slot), at(slot + 1), at(slot + 2));
    }
  });
  return faces.length > 0 ? { vertices, faces } : null;
};

/** Категория элемента из имени материала GLB (`cat:<категория>`): свойства для неё не нужны. */
const categoryOf = (node: THREE.Object3D): string | null => {
  let found: string | null = null;
  node.traverse((object) => {
    if (found !== null || !(object instanceof THREE.Mesh)) return;
    const material = Array.isArray(object.material) ? object.material[0] : object.material;
    const name = (material as THREE.Material | undefined)?.name ?? '';
    if (name.startsWith('cat:')) found = name.slice(4);
  });
  return found;
};

/** Узлы элементов части: ближайшие к корню узлы с именем (GlobalId), сам корень не считается. */
const elementNodes = (root: THREE.Object3D): THREE.Object3D[] => {
  const found: THREE.Object3D[] = [];
  const walk = (node: THREE.Object3D): void => {
    for (const child of node.children) {
      if (child.name !== '') found.push(child);
      else walk(child);
    }
  };
  walk(root);
  return found;
};

/**
 * Часть пакета (разобранная сцена GLB) -> объекты Speckle. Элементы без геометрии пропускаются;
 * свойства берутся из `elements`, если часть элементов загружена.
 */
export interface IPartOptions {
  /** Только эти категории (остальные пропускаются): лёгкий вид всего здания. `null` - все. */
  readonly categories?: ReadonlySet<string> | null;
  /** Этаж части (storey_key): пишется в элемент, чтобы щелчок знал, из какого он этажа. */
  readonly group?: string;
}

export const partToSpeckle = (
  partKey: string,
  discipline: string,
  scene: THREE.Object3D,
  elements: ReadonlyMap<string, IModelElement> | null,
  options: IPartOptions = {},
): ISpeckleResource => {
  const objects: ISpeckleObject[] = [];
  const speckleIds = new Map<string, string>();
  const refs: Array<{ speckle_type: string; referencedId: string }> = [];
  const closure: Record<string, number> = {};
  for (const node of elementNodes(scene)) {
    const info = elements?.get(node.name);
    const category = info?.category ?? categoryOf(node);
    if (options.categories && category !== null && !options.categories.has(category)) continue;
    const mesh = meshOf(node);
    if (mesh === null) continue;
    const id = speckleIdOf(partKey, node.name);
    const meshId = `${id}:mesh`;
    objects.push(
      {
        id: meshId,
        speckle_type: 'Objects.Geometry.Mesh',
        units: 'm',
        vertices: mesh.vertices,
        faces: mesh.faces,
        totalChildrenCount: 0,
      },
      {
        id,
        speckle_type: 'Base',
        name: info?.name ?? node.name,
        applicationId: node.name,
        category,
        storeyKey: options.group ?? null,
        ifcClass: info?.ifc_class ?? null,
        type: info?.type ?? null,
        discipline: info?.discipline ?? discipline,
        properties: { [PROPS_GROUP]: { ...(info?.props ?? {}) } },
        displayValue: [{ speckle_type: 'reference', referencedId: meshId }],
        __closure: { [meshId]: 1 },
      },
    );
    speckleIds.set(node.name, id);
    refs.push({ speckle_type: 'reference', referencedId: id });
    closure[id] = 1;
    closure[meshId] = 2;
  }
  const resource = `part:${partKey}`;
  const root: ISpeckleObject = {
    id: `${resource}:root`,
    speckle_type: 'Base',
    name: resource,
    elements: refs,
    __closure: closure,
  };
  return { resource, discipline, objects: [root, ...objects], speckleIds };
};

export interface ISpeckleViewerOptions {
  /** Щелчок: GlobalId элемента и этаж его части, либо `null` по пустому месту. */
  readonly onPick: (id: string | null, group: string | null) => void;
  /** Часть не разобрана или просмотрщик не запустился. */
  readonly onError: (message: string) => void;
}

export interface ISetContentOptions extends IPartOptions {
  /** Ход загрузки: сколько частей из скольких уже в просмотрщике. */
  readonly onProgress?: (done: number, total: number) => void;
}

export interface ISpeckleModelViewer {
  /** Заменяет содержимое: части (GLB) и свойства их элементов. Возвращает, загрузилось ли хоть что-то. */
  setContent: (
    parts: readonly IModelPartInput[],
    elements: ReadonlyMap<string, IModelElement> | null,
    options?: ISetContentOptions,
  ) => Promise<boolean>;
  setDisciplineVisible: (discipline: string, visible: boolean) => void;
  /** Показать только этажи с номером не выше `level`; `null` - все. */
  setMaxLevel: (level: number | null) => void;
  /** Разнос этажей по вертикали: на сколько метров поднят каждый следующий этаж. */
  setStoreyOffset: (meters: number) => void;
  select: (id: string | null) => void;
  setColorByCategory: (enabled: boolean) => void;
  fit: () => void;
  /** Подлететь камерой к этажу (группе частей), ничего не скрывая. */
  focusGroup: (group: string) => void;
  dispose: () => void;
}

/** Подпись части: если она изменилась у той же части (другой этаж, дисциплина), её грузят заново. */
export const partSignature = (part: IModelPartInput): string =>
  `${part.discipline}|${part.group ?? ''}|${part.level ?? 0}`;

export interface IContentPlan {
  /** Ключи загруженных частей, которые надо выгрузить. */
  readonly remove: readonly string[];
  /** Ключи частей, которые надо загрузить, в порядке `wanted`. */
  readonly add: readonly string[];
  /** Сколько прежних частей остаётся на месте. */
  readonly kept: number;
}

/**
 * Что сделать, чтобы из загруженного получить нужное. Неизменившиеся части (тот же sha256 и та же
 * подпись) остаются: пуш одной дисциплины не перезагружает всё здание. `reloadAll` - полная замена
 * (изменились свойства элементов или фильтр категорий).
 */
export const planContentUpdate = (
  loaded: ReadonlyMap<string, string>,
  wanted: ReadonlyMap<string, string>,
  reloadAll: boolean,
): IContentPlan => {
  const remove: string[] = [];
  let kept = 0;
  for (const [key, signature] of loaded) {
    if (!reloadAll && wanted.get(key) === signature) kept += 1;
    else remove.push(key);
  }
  const removed = new Set(remove);
  const add = [...wanted.keys()].filter((key) => !loaded.has(key) || removed.has(key));
  return { remove, add, kept };
};

/** Просмотрщик на `@speckle/viewer`; библиотека подгружается здесь, а не при открытии страницы. */
export const createSpeckleModelViewer = async (
  host: HTMLElement,
  options: ISpeckleViewerOptions,
): Promise<ISpeckleModelViewer> => {
  const speckle = await import('@speckle/viewer');
  const { ObjectLoader2Factory } = await import('@speckle/objectloader2');
  const { Viewer, DefaultViewerParams, ViewerEvent } = speckle;

  /**
   * В `SpeckleOfflineLoader` версии 2.31 данные не доходят до загрузчика объектов (создаётся
   * пустой), поэтому фабрика подменяется: объекты берутся из памяти.
   */
  class MemoryLoader extends speckle.SpeckleOfflineLoader {
    protected override initObjectLoader(
      _resource: string,
      _authToken?: string,
      _enableCaching?: boolean,
      resourceData?: unknown,
    ): ReturnType<typeof ObjectLoader2Factory.createFromObjects> {
      return ObjectLoader2Factory.createFromObjects(resourceData as ISpeckleObject[]);
    }
  }

  const viewer = new Viewer(host, { ...DefaultViewerParams, showStats: false, verbose: false });
  await viewer.init();
  // Тени в просмотрщике не нужны: ни от солнца, ни «тень на земле» (и сборка кадра дешевле).
  viewer.setLightConfiguration({ castShadow: false, shadowcatcher: false });
  const camera = viewer.createExtension(speckle.CameraController);
  const selection = viewer.createExtension(speckle.SelectionExtension);
  const filtering = viewer.createExtension(speckle.FilteringExtension);

  /** Загруженная часть: что она значит для видимости и разноса и как её выгрузить. */
  interface ILoadedGroup {
    readonly key: string;
    readonly resource: string;
    readonly signature: string;
    readonly group: string;
    readonly discipline: string;
    readonly level: number;
    readonly ids: readonly string[];
  }

  const gltf = new GLTFLoader();
  const hidden = new Set<string>();
  const groups: ILoadedGroup[] = [];
  const speckleIds = new Map<string, string>();
  const levelOf = new Map<string, number>();
  let maxLevel: number | null = null;
  let offsetMeters = 0;
  let colorByCategory = false;
  let lastElements: ReadonlyMap<string, IModelElement> | null = null;
  let lastCategories = '';
  let generation = 0;
  let disposed = false;

  const applyVisibility = (): void => {
    for (const group of groups) {
      const off = hidden.has(group.discipline) || (maxLevel !== null && group.level > maxLevel);
      if (off) filtering.hideObjects([...group.ids], undefined, false);
      else filtering.showObjects([...group.ids], undefined, false);
    }
    viewer.requestRender();
  };

  /** Разнос этажей: каждый объект поднимается на номер своего этажа, умноженный на шаг. */
  const applyOffset = (): void => {
    for (const object of viewer.getRenderer().getObjects()) {
      const level = levelOf.get(object.renderView.renderData.id.replace(/:mesh$/, ''));
      if (level === undefined) continue;
      object.transformTRS({ x: 0, y: 0, z: level * offsetMeters }, undefined, undefined, undefined);
    }
    viewer.requestRender(speckle.UpdateFlags.RENDER_RESET | speckle.UpdateFlags.SHADOWS);
  };

  const applyColors = async (): Promise<void> => {
    if (!colorByCategory) {
      filtering.removeColorFilter();
    } else {
      const properties = await viewer.getObjectProperties();
      const category = properties.find((property) => property.key === 'category');
      if (category !== undefined) filtering.setColorFilter(category);
    }
    viewer.requestRender();
  };

  viewer.on(ViewerEvent.ObjectClicked, (event) => {
    const hit = event?.hits[0];
    if (hit === undefined) {
      options.onPick(null, null);
      return;
    }
    for (let node: typeof hit.node | null = hit.node; node; node = node.parent ?? null) {
      const raw = node.model?.raw as { applicationId?: unknown; storeyKey?: unknown } | undefined;
      if (typeof raw?.applicationId === 'string') {
        options.onPick(raw.applicationId, typeof raw.storeyKey === 'string' ? raw.storeyKey : null);
        return;
      }
    }
    options.onPick(null, null);
  });

  const unloadGroup = async (key: string): Promise<void> => {
    const index = groups.findIndex((group) => group.key === key);
    const group = groups[index];
    if (group === undefined) return;
    groups.splice(index, 1);
    for (const [elementId, id] of [...speckleIds]) {
      if (group.ids.includes(id)) speckleIds.delete(elementId);
    }
    for (const id of group.ids) levelOf.delete(id);
    await viewer.unloadObject(group.resource);
  };

  const applyContent = async (
    token: number,
    parts: readonly IModelPartInput[],
    elements: ReadonlyMap<string, IModelElement> | null,
    content: ISetContentOptions,
  ): Promise<boolean> => {
    const categories = content.categories ? [...content.categories].sort().join(',') : '';
    const reloadAll = elements !== lastElements || categories !== lastCategories;
    lastElements = elements;
    lastCategories = categories;
    const wantedSignatures = new Set(parts.map(partSignature));
    // Содержимое продолжается (те же этажи и дисциплины, обновились сами части): вид не трогаем.
    const continuing = groups.some((group) => wantedSignatures.has(group.signature));
    const plan = planContentUpdate(
      new Map(groups.map((group) => [group.key, group.signature])),
      new Map(parts.map((part) => [part.key, partSignature(part)])),
      reloadAll,
    );
    for (const key of plan.remove) await unloadGroup(key);
    const byKey = new Map(parts.map((part) => [part.key, part]));
    let added = 0;
    for (const key of plan.add) {
      const part = byKey.get(key);
      if (part === undefined) continue;
      if (disposed || token !== generation) return groups.length > 0;
      let resource: ISpeckleResource;
      try {
        const parsed = await gltf.parseAsync(part.buffer, '');
        resource = partToSpeckle(part.key, part.discipline, parsed.scene, elements, {
          ...content,
          group: part.group,
        });
      } catch {
        options.onError('Часть модели не удалось разобрать.');
        continue;
      }
      if (disposed || token !== generation) return groups.length > 0;
      const loader = new MemoryLoader(viewer.getWorldTree(), resource.objects, resource.resource);
      await viewer.loadObject(loader, false);
      const level = part.level ?? 0;
      const ids: string[] = [];
      for (const [elementId, id] of resource.speckleIds) {
        ids.push(id);
        speckleIds.set(elementId, id);
        levelOf.set(id, level);
      }
      groups.push({
        key: part.key,
        resource: resource.resource,
        signature: partSignature(part),
        group: part.group ?? '',
        discipline: part.discipline,
        level,
        ids,
      });
      added += 1;
      content.onProgress?.(added, plan.add.length);
    }
    if (disposed || token !== generation) return groups.length > 0;
    applyVisibility();
    if (offsetMeters !== 0) applyOffset();
    await applyColors();
    // Камеру вписываем, только когда показано другое содержимое (другой этаж, первая загрузка):
    // обновление частей (пуш одной дисциплины) не должно сбрасывать вид, который смотрит человек.
    if (added > 0 && !continuing) camera.setCameraView(undefined, FIT_TRANSITION);
    return groups.length > 0;
  };

  let queue: Promise<unknown> = Promise.resolve();
  const setContent: ISpeckleModelViewer['setContent'] = (parts, elements, content = {}) => {
    generation += 1;
    const token = generation;
    const run = queue.then(() => applyContent(token, parts, elements, content));
    queue = run.catch(() => undefined);
    return run;
  };

  return {
    setContent,
    setDisciplineVisible: (discipline, visible) => {
      if (visible) hidden.delete(discipline);
      else hidden.add(discipline);
      applyVisibility();
    },
    setMaxLevel: (level) => {
      maxLevel = level;
      applyVisibility();
    },
    setStoreyOffset: (meters) => {
      offsetMeters = meters;
      applyOffset();
    },
    select: (id) => {
      const target = id === null ? undefined : speckleIds.get(id);
      if (target === undefined) selection.clearSelection();
      else selection.selectObjects([target]);
      viewer.requestRender();
    },
    setColorByCategory: (enabled) => {
      colorByCategory = enabled;
      void applyColors();
    },
    fit: () => camera.setCameraView(undefined, FIT_TRANSITION),
    focusGroup: (group) => {
      const ids = groups.filter((item) => item.group === group).flatMap((item) => [...item.ids]);
      if (ids.length > 0) camera.setCameraView(ids, FIT_TRANSITION);
    },
    dispose: () => {
      disposed = true;
      generation += 1;
      viewer.dispose();
    },
  };
};
