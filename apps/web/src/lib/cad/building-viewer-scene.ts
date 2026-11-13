import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

import {
  explodeOffsets,
  fitDistance,
  mergeShells,
  extrudeShell,
  viewerBounds,
  type IViewerFloorSpec,
  type IViewerPlan,
} from './building-viewer-geometry';

/**
 * Рендер просмотрщика объекта: перспективная камера и `OrbitControls` вокруг здания из настоящих
 * стен всех этажей. Кадр строится по требованию (смена камеры, размера, стиля, модели), постоянного
 * цикла нет; инерция - только пока идёт движение и если не включён `prefers-reduced-motion`.
 * Все ресурсы освобождаются в `dispose`. Модуль грузится вместе с просмотрщиком: `three` не попадает
 * в чанк страницы.
 */

export interface IBuildingViewerColors {
  readonly accent: string;
  readonly muted: string;
  readonly slab: string;
  readonly masonry: string;
  readonly monolith: string;
}

const FALLBACK_COLOR = 'gray';

/** Цвета только из токенов темы: плита, кладка и монолит - как в 3D этажа. */
export const readBuildingViewerColors = (): IBuildingViewerColors => {
  if (typeof document === 'undefined') {
    return {
      accent: FALLBACK_COLOR,
      muted: FALLBACK_COLOR,
      slab: FALLBACK_COLOR,
      masonry: FALLBACK_COLOR,
      monolith: FALLBACK_COLOR,
    };
  }
  const style = getComputedStyle(document.documentElement);
  const token = (name: string): string => style.getPropertyValue(name).trim() || FALLBACK_COLOR;
  return {
    accent: token('--accent'),
    muted: token('--muted'),
    slab: token('--border-strong'),
    masonry: token('--cad-construction-masonry'),
    monolith: token('--cad-construction-monolith'),
  };
};

export interface IBuildingViewerOptions {
  readonly reducedMotion: boolean;
  /** Наведение (только мышь): ключ этажа или `null`; точка - от угла холста. */
  readonly onHover: (key: string | null, anchor: { x: number; y: number } | null) => void;
  /** Щелчок или касание (не перетаскивание) по этажу. */
  readonly onSelect: (key: string) => void;
  /** Двойной щелчок или двойное касание по этажу. */
  readonly onOpenDetail: (key: string) => void;
}

export interface IBuildingViewer {
  /** Показать модель; прежняя освобождается. Камера вписывается, когда набор этажей сменился. */
  setPlan: (plan: IViewerPlan | null, colors: IBuildingViewerColors) => void;
  /** Новые цвета темы без пересборки модели и без сдвига камеры. */
  setColors: (colors: IBuildingViewerColors) => void;
  /** Выбранный этаж (акцент) и наведённый (подсветка); остальные при выборе приглушаются. */
  setStyle: (selectedKey: string | null, hoverKey: string | null) => void;
  setExploded: (exploded: boolean) => void;
  /** Здание целиком в кадре, направление взгляда сохраняется. */
  fit: () => void;
  dispose: () => void;
}

const FOV_DEG = 40;
/** Порог, после которого нажатие считается перетаскиванием, px. */
const CLICK_SLOP_PX = 6;
const DOUBLE_TAP_MS = 350;
/** Разнесение этажей идёт не дольше 250 мс. */
const EXPLODE_MS = 220;
/** Камера не опускается ниже горизонта цели: под землю не уйти. */
const MAX_POLAR = Math.PI / 2 - 0.03;
const MIN_DISTANCE_M = 2;
/** Изометрия по умолчанию: с юга (+Z сцены) и сверху, как «лист». */
const START_DIRECTION = new THREE.Vector3(0.7, 0.8, 1).normalize();

type Part = 'slab' | 'monolith' | 'masonry' | 'volume';

interface IFloorEntry {
  readonly key: string;
  readonly group: THREE.Group;
  /** Смещение по высоте при полном разнесении, м. */
  readonly offset: number;
  readonly meshes: ReadonlyMap<Part, THREE.Mesh<THREE.BufferGeometry, THREE.MeshLambertMaterial>>;
}

/** Разнесение этажей: коэффициент, цель камеры и расстояние плывут от прежних значений к новым. */
interface IExplodeAnim {
  readonly from: number;
  readonly to: number;
  readonly start: number;
  readonly fromTarget: THREE.Vector3;
  readonly toTarget: THREE.Vector3;
  readonly fromDistance: number;
  readonly toDistance: number;
}

type FloorMesh = THREE.Mesh<THREE.BufferGeometry, THREE.MeshLambertMaterial>;

const makeMesh = (geometry: THREE.BufferGeometry, key: string): FloorMesh => {
  const mesh = new THREE.Mesh(geometry, new THREE.MeshLambertMaterial({ transparent: true }));
  mesh.userData.floorKey = key;
  return mesh;
};

/** Меши этажа: плита, стены двух материалов (слиянием), а без стен - прозрачный объём этажа. */
const buildFloor = (spec: IViewerFloorSpec, offset: number): IFloorEntry | null => {
  const meshes = new Map<Part, FloorMesh>();
  const slab = extrudeShell(spec.shell, spec.slabBottom, spec.slabTop);
  if (slab !== null) meshes.set('slab', makeMesh(slab, spec.key));
  for (const material of ['monolith', 'masonry'] as const) {
    const shells = spec.walls.filter((wall) => wall.material === material).map((wall) => wall.shell);
    const geometry = mergeShells(shells, spec.slabTop, spec.wallTop);
    if (geometry !== null) meshes.set(material, makeMesh(geometry, spec.key));
  }
  if (!meshes.has('monolith') && !meshes.has('masonry')) {
    const volume = extrudeShell(spec.shell, spec.slabTop, spec.volumeTop);
    if (volume !== null) {
      const mesh = makeMesh(volume, spec.key);
      mesh.material.depthWrite = false;
      meshes.set('volume', mesh);
    }
  }
  if (meshes.size === 0) return null;
  const group = new THREE.Group();
  group.userData.floorKey = spec.key;
  for (const mesh of meshes.values()) group.add(mesh);
  return { key: spec.key, group, offset, meshes };
};

export const createBuildingViewer = (host: HTMLElement, options: IBuildingViewerOptions): IBuildingViewer => {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x000000, 0);
  const dom = renderer.domElement;
  dom.className = 'block h-full w-full touch-none';
  host.appendChild(dom);

  const scene = new THREE.Scene();
  scene.add(new THREE.AmbientLight(0xffffff, 1.5));
  const sun = new THREE.DirectionalLight(0xffffff, 2);
  sun.position.set(1, 2, 1.5);
  scene.add(sun);
  const root = new THREE.Group();
  scene.add(root);

  const camera = new THREE.PerspectiveCamera(FOV_DEG, 1, 0.1, 1000);
  camera.position.copy(START_DIRECTION).multiplyScalar(10);
  const controls = new OrbitControls(camera, dom);
  controls.enableDamping = !options.reducedMotion;
  controls.screenSpacePanning = true;
  controls.maxPolarAngle = MAX_POLAR;

  let plan: IViewerPlan | null = null;
  let entries: IFloorEntry[] = [];
  let pickTargets: THREE.Object3D[] = [];
  let colors: IBuildingViewerColors = readBuildingViewerColors();
  let selectedKey: string | null = null;
  let hoverKey: string | null = null;
  let exploded = false;
  let factor = 0;
  let anim: IExplodeAnim | null = null;
  let signature = '';
  let groundY = -Infinity;

  let disposed = false;
  let frame = 0;
  const scratch = new THREE.Color();
  const accentColor = new THREE.Color();

  const applyOffsets = (): void => {
    for (const entry of entries) entry.group.position.y = entry.offset * factor;
    root.updateMatrixWorld(true);
  };

  const render = (): void => {
    frame = 0;
    if (disposed) return;
    if (anim !== null) {
      const t = Math.min(1, (performance.now() - anim.start) / EXPLODE_MS);
      const eased = 1 - (1 - t) * (1 - t);
      factor = anim.from + (anim.to - anim.from) * eased;
      applyOffsets();
      // Камера плывёт вместе с этажами: направление взгляда прежнее, центр и расстояние - к новым.
      const direction = camera.position.clone().sub(controls.target).normalize();
      controls.target.lerpVectors(anim.fromTarget, anim.toTarget, eased);
      const distance = anim.fromDistance + (anim.toDistance - anim.fromDistance) * eased;
      camera.position.copy(controls.target).addScaledVector(direction, distance);
      if (t >= 1) anim = null;
    }
    const moving = controls.update();
    renderer.render(scene, camera);
    if (moving || anim !== null) requestRender();
  };
  function requestRender(): void {
    if (disposed || frame !== 0) return;
    frame = requestAnimationFrame(render);
  }
  controls.addEventListener('change', () => {
    // Панорама не уводит цель ниже низа здания.
    if (controls.target.y < groundY) {
      const lift = groundY - controls.target.y;
      controls.target.y += lift;
      camera.position.y += lift;
    }
    requestRender();
  });

  /** Расстояние камеры и цель для здания в заданном состоянии разнесения. */
  const framing = (isExploded: boolean): { target: THREE.Vector3; distance: number; radius: number } | null => {
    if (plan === null) return null;
    const bounds = viewerBounds(plan, isExploded);
    const aspect = Math.max(1, host.clientWidth) / Math.max(1, host.clientHeight);
    return {
      target: new THREE.Vector3(...bounds.center),
      distance: fitDistance(bounds.radius, FOV_DEG, aspect),
      radius: bounds.radius,
    };
  };

  const limitCamera = (distance: number, radius: number): void => {
    camera.near = Math.max(0.05, distance * 0.01);
    camera.far = (distance + radius) * 10;
    camera.updateProjectionMatrix();
    controls.minDistance = MIN_DISTANCE_M;
    controls.maxDistance = distance * 6;
  };

  const fit = (direction: THREE.Vector3 | null): void => {
    const frameInfo = framing(exploded);
    if (frameInfo === null) return;
    anim = null;
    const look = direction ?? camera.position.clone().sub(controls.target).normalize();
    limitCamera(frameInfo.distance, frameInfo.radius);
    controls.target.copy(frameInfo.target);
    camera.position.copy(frameInfo.target).addScaledVector(look, frameInfo.distance);
    camera.lookAt(frameInfo.target);
    controls.update();
    requestRender();
  };

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

  const disposeFloors = (): void => {
    for (const entry of entries) {
      root.remove(entry.group);
      for (const mesh of entry.meshes.values()) {
        mesh.geometry.dispose();
        mesh.material.dispose();
      }
    }
    entries = [];
    pickTargets = [];
  };

  const applyStyle = (): void => {
    accentColor.set(colors.accent);
    const dimOthers = selectedKey !== null;
    for (const entry of entries) {
      const selected = entry.key === selectedKey;
      const hovered = !selected && entry.key === hoverKey;
      const dimmed = dimOthers && !selected;
      for (const [part, mesh] of entry.meshes) {
        const base = part === 'volume' ? colors.muted : colors[part];
        scratch.set(base);
        if (selected) scratch.copy(accentColor);
        else if (hovered) scratch.lerp(accentColor, 0.55);
        mesh.material.color.copy(scratch);
        let opacity = 1;
        if (part === 'volume') opacity = selected ? 0.3 : hovered ? 0.35 : dimmed ? 0.05 : 0.12;
        else if (dimmed) opacity = 0.3;
        mesh.material.opacity = opacity;
        // Смена прозрачности меняет вариант шейдера (OPAQUE): без `needsUpdate` он не перекомпилируется.
        if (mesh.material.transparent !== opacity < 1) {
          mesh.material.transparent = opacity < 1;
          mesh.material.needsUpdate = true;
        }
        mesh.material.depthWrite = part === 'volume' ? false : opacity >= 1;
      }
    }
    requestRender();
  };

  // Выбор мышью: луч по мешам этажей -> ключ этажа.
  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  const pickAt = (clientX: number, clientY: number): string | null => {
    const rect = dom.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0 || pickTargets.length === 0) return null;
    ndc.set(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    root.updateMatrixWorld(true);
    raycaster.setFromCamera(ndc, camera);
    const hit = raycaster.intersectObjects(pickTargets, false)[0];
    const key: unknown = hit?.object.userData.floorKey;
    return typeof key === 'string' ? key : null;
  };

  let down: { x: number; y: number; moved: boolean } | null = null;
  let lastTap: { key: string; at: number } | null = null;
  let hoverFrame = 0;
  let hoverPoint: { x: number; y: number } | null = null;
  const flushHover = (): void => {
    hoverFrame = 0;
    const point = hoverPoint;
    if (disposed || point === null || down !== null) return;
    const key = pickAt(point.x, point.y);
    const rect = dom.getBoundingClientRect();
    options.onHover(key, key === null ? null : { x: point.x - rect.left, y: point.y - rect.top });
  };
  const onDown = (event: PointerEvent): void => {
    options.onHover(null, null);
    down = event.button === 0 ? { x: event.clientX, y: event.clientY, moved: false } : null;
  };
  const onMove = (event: PointerEvent): void => {
    if (down !== null) {
      if (Math.hypot(event.clientX - down.x, event.clientY - down.y) > CLICK_SLOP_PX) down.moved = true;
      return;
    }
    if (event.pointerType === 'touch' || event.buttons !== 0) return;
    hoverPoint = { x: event.clientX, y: event.clientY };
    if (hoverFrame === 0) hoverFrame = requestAnimationFrame(flushHover);
  };
  const onUp = (event: PointerEvent): void => {
    const start = down;
    down = null;
    if (start === null || start.moved) return;
    const key = pickAt(event.clientX, event.clientY);
    if (key === null) return;
    const now = performance.now();
    if (lastTap !== null && lastTap.key === key && now - lastTap.at < DOUBLE_TAP_MS) {
      lastTap = null;
      options.onOpenDetail(key);
      return;
    }
    lastTap = { key, at: now };
    options.onSelect(key);
  };
  const onCancel = (): void => {
    down = null;
  };
  const onLeave = (): void => {
    hoverPoint = null;
    options.onHover(null, null);
  };
  dom.addEventListener('pointerdown', onDown);
  dom.addEventListener('pointermove', onMove);
  dom.addEventListener('pointerup', onUp);
  dom.addEventListener('pointercancel', onCancel);
  dom.addEventListener('pointerleave', onLeave);

  return {
    setPlan: (nextPlan, nextColors) => {
      disposeFloors();
      colors = nextColors;
      plan = nextPlan;
      if (nextPlan === null) {
        signature = '';
        requestRender();
        return;
      }
      const offsets = explodeOffsets(nextPlan);
      for (const spec of nextPlan.floors) {
        const entry = buildFloor(spec, offsets.get(spec.key) ?? 0);
        if (entry === null) continue;
        root.add(entry.group);
        entries.push(entry);
        pickTargets.push(...entry.meshes.values());
      }
      groundY = Math.min(...nextPlan.floors.map((spec) => spec.slabBottom));
      applyOffsets();
      applyStyle();
      // Камера вписывается только при смене набора этажей: обновление данных вид не сбрасывает.
      const next = nextPlan.floors.map((spec) => spec.key).join('|');
      if (next !== signature) {
        signature = next;
        fit(START_DIRECTION);
      }
    },
    setColors: (nextColors) => {
      colors = nextColors;
      applyStyle();
    },
    setStyle: (nextSelected, nextHover) => {
      selectedKey = nextSelected;
      hoverKey = nextHover;
      applyStyle();
    },
    setExploded: (next) => {
      if (next === exploded) return;
      exploded = next;
      const to = framing(next);
      if (to === null || entries.length === 0) return;
      limitCamera(to.distance, to.radius);
      if (options.reducedMotion) {
        factor = next ? 1 : 0;
        applyOffsets();
        fit(null);
        return;
      }
      anim = {
        from: factor,
        to: next ? 1 : 0,
        start: performance.now(),
        fromTarget: controls.target.clone(),
        toTarget: to.target,
        fromDistance: camera.position.distanceTo(controls.target),
        toDistance: to.distance,
      };
      requestRender();
    },
    fit: () => fit(null),
    dispose: () => {
      disposed = true;
      if (frame !== 0) cancelAnimationFrame(frame);
      if (hoverFrame !== 0) cancelAnimationFrame(hoverFrame);
      observer.disconnect();
      dom.removeEventListener('pointerdown', onDown);
      dom.removeEventListener('pointermove', onMove);
      dom.removeEventListener('pointerup', onUp);
      dom.removeEventListener('pointercancel', onCancel);
      dom.removeEventListener('pointerleave', onLeave);
      controls.dispose();
      disposeFloors();
      renderer.dispose();
      renderer.forceContextLoss();
      dom.remove();
    },
  };
};
