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
export const partToSpeckle = (
  partKey: string,
  discipline: string,
  scene: THREE.Object3D,
  elements: ReadonlyMap<string, IModelElement> | null,
): ISpeckleResource => {
  const objects: ISpeckleObject[] = [];
  const speckleIds = new Map<string, string>();
  const refs: Array<{ speckle_type: string; referencedId: string }> = [];
  const closure: Record<string, number> = {};
  for (const node of elementNodes(scene)) {
    const mesh = meshOf(node);
    if (mesh === null) continue;
    const info = elements?.get(node.name);
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
        category: info?.category ?? null,
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
  /** Щелчок: GlobalId элемента или `null` по пустому месту. */
  readonly onPick: (id: string | null) => void;
  /** Часть не разобрана или просмотрщик не запустился. */
  readonly onError: (message: string) => void;
}

export interface ISpeckleModelViewer {
  /** Заменяет содержимое: части (GLB) и свойства их элементов. Возвращает, загрузилось ли хоть что-то. */
  setContent: (
    parts: readonly IModelPartInput[],
    elements: ReadonlyMap<string, IModelElement> | null,
  ) => Promise<boolean>;
  setDisciplineVisible: (discipline: string, visible: boolean) => void;
  select: (id: string | null) => void;
  setColorByCategory: (enabled: boolean) => void;
  fit: () => void;
  dispose: () => void;
}

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
  const camera = viewer.createExtension(speckle.CameraController);
  const selection = viewer.createExtension(speckle.SelectionExtension);
  const filtering = viewer.createExtension(speckle.FilteringExtension);

  const gltf = new GLTFLoader();
  const hidden = new Set<string>();
  const byDiscipline = new Map<string, string[]>();
  const speckleIds = new Map<string, string>();
  let resources: string[] = [];
  let colorByCategory = false;
  let generation = 0;
  let disposed = false;

  const applyVisibility = (): void => {
    for (const [discipline, ids] of byDiscipline) {
      if (hidden.has(discipline)) filtering.hideObjects(ids, undefined, false);
      else filtering.showObjects(ids, undefined, false);
    }
    viewer.requestRender();
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
      options.onPick(null);
      return;
    }
    for (let node: typeof hit.node | null = hit.node; node; node = node.parent ?? null) {
      const raw = node.model?.raw as { applicationId?: unknown } | undefined;
      if (typeof raw?.applicationId === 'string') {
        options.onPick(raw.applicationId);
        return;
      }
    }
    options.onPick(null);
  });

  const unloadAll = async (): Promise<void> => {
    const previous = resources;
    resources = [];
    byDiscipline.clear();
    speckleIds.clear();
    for (const resource of previous) await viewer.unloadObject(resource);
  };

  const setContent: ISpeckleModelViewer['setContent'] = async (parts, elements) => {
    generation += 1;
    const token = generation;
    await unloadAll();
    let loaded = false;
    for (const part of parts) {
      if (disposed || token !== generation) return loaded;
      let resource: ISpeckleResource;
      try {
        const parsed = await gltf.parseAsync(part.buffer, '');
        resource = partToSpeckle(part.key, part.discipline, parsed.scene, elements);
      } catch {
        options.onError('Часть модели не удалось разобрать.');
        continue;
      }
      if (disposed || token !== generation) return loaded;
      const loader = new MemoryLoader(viewer.getWorldTree(), resource.objects, resource.resource);
      await viewer.loadObject(loader, false);
      resources.push(resource.resource);
      const ids = byDiscipline.get(part.discipline) ?? [];
      for (const [elementId, id] of resource.speckleIds) {
        ids.push(id);
        speckleIds.set(elementId, id);
      }
      byDiscipline.set(part.discipline, ids);
      loaded = true;
    }
    if (disposed || token !== generation) return loaded;
    applyVisibility();
    await applyColors();
    if (loaded) camera.setCameraView(undefined, FIT_TRANSITION);
    return loaded;
  };

  return {
    setContent,
    setDisciplineVisible: (discipline, visible) => {
      if (visible) hidden.delete(discipline);
      else hidden.add(discipline);
      applyVisibility();
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
    dispose: () => {
      disposed = true;
      generation += 1;
      viewer.dispose();
    },
  };
};
