import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

import { attachPivotOrbit } from '@/lib/cad/pivot-orbit';

/**
 * Рендер 3D этажа модели (ADR-0053): части GLB пакета QMP по дисциплинам. Геометрия уже в метрах и
 * в осях glTF (Y вверх), перевод из системы здания сделан выгрузчиком. Кадр строится по требованию,
 * цикла нет; все ресурсы освобождаются в `dispose`.
 *
 * Элемент пакета - узел GLB с именем `id`: выбор щелчком находит узел вверх по родителям от
 * попавшего меша; выбранный элемент подсвечивается заменой материалов, прежние возвращаются
 * при снятии выбора.
 */

const FOV_DEG = 45;
const CLICK_SLOP_PX = 4;
const START_DIRECTION = new THREE.Vector3(1, 0.9, 1.2).normalize();
const FIT_MARGIN = 1.25;

export interface IModelPartInput {
  /** Ключ части (sha256): одна и та же часть второй раз не разбирается. */
  readonly key: string;
  readonly discipline: string;
  readonly buffer: ArrayBuffer;
  /** Этаж части (storey_key): по нему просмотрщик Speckle разносит и скрывает этажи. */
  readonly group?: string;
  /** Номер этажа снизу вверх (0 - нижний). */
  readonly level?: number;
}

/** Дисциплины «Всего дома» до первого выбора: АР, если есть, иначе первая по алфавиту. */
export const defaultHouseDisciplines = (all: readonly string[]): ReadonlySet<string> =>
  new Set(all.includes('ARCH') ? ['ARCH'] : all.slice(0, 1));

export interface IModelViewerColors {
  readonly accent: string;
  readonly background: string;
}

export interface IModelViewerOptions {
  readonly reducedMotion: boolean;
  readonly colors: IModelViewerColors;
  /** Щелчок: id элемента или `null` по пустому месту. */
  readonly onPick: (id: string | null) => void;
  /** Часть GLB не разобрана. */
  readonly onPartError: (key: string) => void;
}

export interface IModelViewer {
  setParts: (parts: readonly IModelPartInput[]) => void;
  setDisciplineVisible: (discipline: string, visible: boolean) => void;
  select: (id: string | null) => void;
  fit: () => void;
  setColors: (colors: IModelViewerColors) => void;
  dispose: () => void;
}

interface ILoadedPart {
  readonly discipline: string;
  readonly group: THREE.Group;
}

const disposeMaterial = (material: THREE.Material | THREE.Material[]): void => {
  for (const item of Array.isArray(material) ? material : [material]) item.dispose();
};

const disposeTree = (root: THREE.Object3D): void => {
  root.traverse((object) => {
    if (object instanceof THREE.Mesh) {
      object.geometry.dispose();
      disposeMaterial(object.material);
    }
  });
};

/** Узел элемента: ближайший к мешу предок (или он сам) с непустым именем. */
export const elementIdOf = (object: THREE.Object3D | null): string | null => {
  for (let node = object; node !== null; node = node.parent) {
    if (node.name !== '') return node.name;
    if (node.userData.modelRoot === true) return null;
  }
  return null;
};

export const createModelViewer = (
  host: HTMLElement,
  options: IModelViewerOptions,
): IModelViewer => {
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  const dom = renderer.domElement;
  dom.className = 'block h-full w-full touch-none';
  host.appendChild(dom);

  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x777777, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.8);
  sun.position.set(1, 2, 1.5);
  scene.add(sun);
  const root = new THREE.Group();
  root.userData.modelRoot = true;
  scene.add(root);

  const camera = new THREE.PerspectiveCamera(FOV_DEG, 1, 0.05, 2000);
  camera.position.copy(START_DIRECTION).multiplyScalar(30);
  const controls = new OrbitControls(camera, dom);
  controls.enableDamping = !options.reducedMotion;
  controls.screenSpacePanning = true;

  const loader = new GLTFLoader();
  const loaded = new Map<string, ILoadedPart>();
  const hidden = new Set<string>();
  const accent = new THREE.Color();
  let highlight: THREE.MeshStandardMaterial | null = null;
  let selectedId: string | null = null;
  const swapped = new Map<THREE.Mesh, THREE.Material | THREE.Material[]>();
  let disposed = false;
  let frame = 0;
  let generation = 0;

  const render = (): void => {
    frame = 0;
    if (disposed) return;
    controls.update();
    renderer.render(scene, camera);
  };
  const requestRender = (): void => {
    if (frame === 0 && !disposed) frame = requestAnimationFrame(render);
  };
  controls.addEventListener('change', requestRender);

  const resize = (): void => {
    const width = Math.max(1, host.clientWidth);
    const height = Math.max(1, host.clientHeight);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    requestRender();
  };
  const observer = new ResizeObserver(resize);
  observer.observe(host);
  resize();

  const setColors = (colors: IModelViewerColors): void => {
    accent.set(colors.accent);
    renderer.setClearColor(new THREE.Color(colors.background), 1);
    highlight?.color.set(colors.accent);
    highlight?.emissive.set(colors.accent);
    requestRender();
  };
  setColors(options.colors);

  const visibleTargets = (): THREE.Object3D[] => {
    const targets: THREE.Object3D[] = [];
    for (const part of loaded.values()) {
      if (!hidden.has(part.discipline)) targets.push(part.group);
    }
    return targets;
  };

  const raycaster = new THREE.Raycaster();
  const rayHit = (clientX: number, clientY: number): THREE.Intersection | null => {
    const rect = dom.getBoundingClientRect();
    const pointer = new THREE.Vector2(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1,
    );
    raycaster.setFromCamera(pointer, camera);
    return raycaster.intersectObjects(visibleTargets(), true)[0] ?? null;
  };

  const pivotOrbit = attachPivotOrbit({
    camera,
    controls,
    dom,
    scene,
    pickPoint: (clientX, clientY) => rayHit(clientX, clientY)?.point.clone() ?? null,
    markerColor: () => accent,
    onChange: requestRender,
  });

  let down: { x: number; y: number } | null = null;
  const onPointerDown = (event: PointerEvent): void => {
    down = { x: event.clientX, y: event.clientY };
  };
  const onPointerUp = (event: PointerEvent): void => {
    const start = down;
    down = null;
    if (start === null || event.button !== 0 || event.shiftKey) return;
    if (Math.hypot(event.clientX - start.x, event.clientY - start.y) > CLICK_SLOP_PX) return;
    options.onPick(elementIdOf(rayHit(event.clientX, event.clientY)?.object ?? null));
  };
  dom.addEventListener('pointerdown', onPointerDown);
  dom.addEventListener('pointerup', onPointerUp);

  const restoreSelection = (): void => {
    for (const [mesh, material] of swapped) mesh.material = material;
    swapped.clear();
  };

  const applySelection = (): void => {
    restoreSelection();
    if (selectedId === null) return;
    highlight ??= new THREE.MeshStandardMaterial({
      color: accent,
      emissive: accent,
      emissiveIntensity: 0.55,
      roughness: 0.6,
    });
    for (const part of loaded.values()) {
      const node = part.group.getObjectByName(selectedId);
      node?.traverse((object) => {
        if (object instanceof THREE.Mesh) {
          swapped.set(object, object.material);
          object.material = highlight as THREE.MeshStandardMaterial;
        }
      });
    }
  };

  const fit = (): void => {
    const box = new THREE.Box3();
    for (const part of loaded.values()) {
      if (!hidden.has(part.discipline)) box.expandByObject(part.group);
    }
    if (box.isEmpty()) return;
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const distance = (sphere.radius / Math.sin(THREE.MathUtils.degToRad(FOV_DEG / 2))) * FIT_MARGIN;
    controls.target.copy(sphere.center);
    camera.position.copy(sphere.center).addScaledVector(START_DIRECTION, distance);
    camera.near = Math.max(0.05, distance / 500);
    camera.far = distance * 20;
    camera.updateProjectionMatrix();
    controls.update();
    requestRender();
  };

  const removePart = (key: string): void => {
    const part = loaded.get(key);
    if (part === undefined) return;
    root.remove(part.group);
    disposeTree(part.group);
    loaded.delete(key);
  };

  const addPart = async (input: IModelPartInput, token: number): Promise<boolean> => {
    try {
      const gltf = await loader.parseAsync(input.buffer, '');
      if (disposed || token !== generation) {
        disposeTree(gltf.scene);
        return false;
      }
      const group = new THREE.Group();
      group.add(gltf.scene);
      group.visible = !hidden.has(input.discipline);
      root.add(group);
      loaded.set(input.key, { discipline: input.discipline, group });
      return true;
    } catch {
      options.onPartError(input.key);
      return false;
    }
  };

  const setParts = (parts: readonly IModelPartInput[]): void => {
    generation += 1;
    const token = generation;
    const wanted = new Set(parts.map((part) => part.key));
    for (const key of [...loaded.keys()]) if (!wanted.has(key)) removePart(key);
    const fresh = parts.filter((part) => !loaded.has(part.key));
    void Promise.all(fresh.map((part) => addPart(part, token))).then((added) => {
      if (disposed || token !== generation) return;
      applySelection();
      if (added.some(Boolean)) fit();
      else requestRender();
    });
    applySelection();
    requestRender();
  };

  return {
    setParts,
    setDisciplineVisible: (discipline, visible) => {
      if (visible) hidden.delete(discipline);
      else hidden.add(discipline);
      for (const part of loaded.values()) {
        if (part.discipline === discipline) part.group.visible = visible;
      }
      requestRender();
    },
    select: (id) => {
      selectedId = id;
      applySelection();
      requestRender();
    },
    fit,
    setColors,
    dispose: () => {
      disposed = true;
      generation += 1;
      if (frame !== 0) cancelAnimationFrame(frame);
      observer.disconnect();
      dom.removeEventListener('pointerdown', onPointerDown);
      dom.removeEventListener('pointerup', onPointerUp);
      pivotOrbit.dispose();
      controls.dispose();
      restoreSelection();
      for (const key of [...loaded.keys()]) removePart(key);
      highlight?.dispose();
      renderer.dispose();
      dom.remove();
    },
  };
};
