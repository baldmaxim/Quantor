import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

import {
  explodeOffsets,
  fitDistance,
  viewerBounds,
  wallIdAtFace,
  type IViewerFloorSpec,
  type IViewerPlan,
  type IViewerWall,
} from './building-viewer-geometry';
import { buildFloor, wallRanges, type IFloorEntry } from './building-viewer-floor';
import { readBuildingViewerColors, type IBuildingViewerColors } from './building-viewer-colors';
import { createGroupLabels } from './building-viewer-labels';
import { createWallOverlay, disposeWallOverlay, type OverlayKind } from './building-viewer-overlay';
import { attachPivotOrbit } from './pivot-orbit';

/**
 * Рендер просмотрщика объекта: перспективная камера и `OrbitControls` вокруг здания из настоящих
 * стен всех этажей. Кадр строится по требованию (смена камеры, размера, стиля, модели), постоянного
 * цикла нет; инерция - только пока идёт движение и если не включён `prefers-reduced-motion`.
 * Все ресурсы освобождаются в `dispose`. Модуль грузится вместе с просмотрщиком: `three` не попадает
 * в чанк страницы.
 *
 * Выбор конструкции: слитый меш стен хранит диапазоны треугольников по конструкциям, луч по
 * `faceIndex` находит конструкцию; выбранная и наведённая конструкции подсвечиваются отдельными мешами.
 */

export interface IBuildingViewerOptions {
  readonly reducedMotion: boolean;
  /** Наведение (только мышь): ключ этажа или `null`; точка - от угла холста. */
  readonly onHover: (key: string | null, anchor: { x: number; y: number } | null) => void;
  /** Щелчок или касание (не перетаскивание) по этажу. */
  readonly onSelect: (key: string) => void;
  /** Щелчок по стене уже выбранного этажа - конструкция; `null` - щелчок в пустоту, выбор конструкции снят. */
  readonly onSelectConstruction: (id: string | null) => void;
  /** Двойной щелчок или двойное касание по этажу. */
  readonly onOpenDetail: (key: string) => void;
}

export interface IBuildingViewer {
  /** Показать модель; прежняя освобождается. Камера вписывается, когда набор этажей сменился. */
  setPlan: (plan: IViewerPlan | null, colors: IBuildingViewerColors) => void;
  /** Новые цвета темы без пересборки модели и без сдвига камеры. */
  setColors: (colors: IBuildingViewerColors) => void;
  /**
   * Выбранный этаж (акцент), наведённый (подсветка) и выбранная конструкция этого этажа; остальные
   * этажи при выборе приглушаются.
   */
  setStyle: (selectedKey: string | null, hoverKey: string | null, constructionId?: string | null) => void;
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
  let constructionId: string | null = null;
  let hoverWallId: string | null = null;
  /** Стены этажей для подсветки: ключ `этаж|конструкция`. */
  let wallIndex = new Map<string, { spec: IViewerFloorSpec; wall: IViewerWall }>();
  const overlays: Record<OverlayKind, THREE.Group | null> = { selected: null, hover: null };
  let exploded = false;
  let factor = 0;
  let anim: IExplodeAnim | null = null;
  let signature = '';
  let groundY = -Infinity;

  let disposed = false;
  let frame = 0;
  const labels = createGroupLabels(host);
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
    labels.update(camera, host.clientWidth, host.clientHeight, (key) => {
      const entry = entries.find((item) => item.key === key);
      return entry === undefined ? 0 : entry.offset * factor;
    });
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

  const syncOverlay = (kind: OverlayKind, wallId: string | null): void => {
    const previous = overlays[kind];
    if (previous !== null) disposeWallOverlay(previous);
    overlays[kind] = null;
    const item = wallId !== null && selectedKey !== null ? wallIndex.get(`${selectedKey}|${wallId}`) : undefined;
    const entry = item === undefined ? undefined : entries.find((candidate) => candidate.key === item.spec.key);
    if (item === undefined || entry === undefined) return;
    const group = createWallOverlay(
      { shell: item.wall.shell, yBottom: item.spec.slabTop, yTop: item.spec.wallTop },
      kind,
      colors.accent,
    );
    if (group === null) return;
    entry.group.add(group);
    overlays[kind] = group;
  };
  const syncOverlays = (): void => {
    syncOverlay('selected', constructionId);
    syncOverlay('hover', hoverWallId === constructionId ? null : hoverWallId);
    requestRender();
  };

  const disposeFloors = (): void => {
    for (const kind of ['selected', 'hover'] as const) {
      const overlay = overlays[kind];
      if (overlay !== null) disposeWallOverlay(overlay);
      overlays[kind] = null;
    }
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
        // Выбрана конструкция: стены этажа остаются своего цвета, чтобы подсветка конструкции была видна.
        const quiet = selected && constructionId !== null && (part === 'monolith' || part === 'masonry');
        if (quiet) scratch.lerp(accentColor, 0.15);
        else if (selected) scratch.copy(accentColor);
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
    syncOverlays();
  };

  // Выбор мышью: луч по мешам этажей -> ключ этажа и, если попали в стену, её конструкция.
  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  const rayHit = (clientX: number, clientY: number): THREE.Intersection | null => {
    const rect = dom.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0 || pickTargets.length === 0) return null;
    ndc.set(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    root.updateMatrixWorld(true);
    raycaster.setFromCamera(ndc, camera);
    return raycaster.intersectObjects(pickTargets, false)[0] ?? null;
  };
  const pivotOrbit = attachPivotOrbit({
    camera,
    controls,
    dom,
    scene,
    pickPoint: (clientX, clientY) => rayHit(clientX, clientY)?.point.clone() ?? null,
    markerColor: () => colors.accent,
    onChange: requestRender,
  });
  const pickAt = (clientX: number, clientY: number): { key: string; wallId: string | null } | null => {
    const hit = rayHit(clientX, clientY);
    const key: unknown = hit?.object.userData.floorKey;
    if (hit === null || typeof key !== 'string') return null;
    const ranges = wallRanges.get(hit.object);
    return { key, wallId: ranges === undefined ? null : wallIdAtFace(ranges, hit.faceIndex) };
  };
  const setHoverWall = (id: string | null): void => {
    if (id === hoverWallId) return;
    hoverWallId = id;
    syncOverlay('hover', hoverWallId === constructionId ? null : hoverWallId);
    requestRender();
  };

  let down: { x: number; y: number; moved: boolean } | null = null;
  let lastTap: { target: string; at: number } | null = null;
  let hoverFrame = 0;
  let hoverPoint: { x: number; y: number } | null = null;
  const flushHover = (): void => {
    hoverFrame = 0;
    const point = hoverPoint;
    if (disposed || point === null || down !== null) return;
    const hit = pickAt(point.x, point.y);
    const rect = dom.getBoundingClientRect();
    // Лёгкая подсветка конструкции - только у стен уже выбранного этажа.
    setHoverWall(hit !== null && hit.key === selectedKey ? hit.wallId : null);
    options.onHover(hit?.key ?? null, hit === null ? null : { x: point.x - rect.left, y: point.y - rect.top });
  };
  const onDown = (event: PointerEvent): void => {
    options.onHover(null, null);
    setHoverWall(null);
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
    const hit = pickAt(event.clientX, event.clientY);
    if (hit === null) {
      // Клик в пустоту снимает выбор конструкции; этаж остаётся.
      if (constructionId !== null) options.onSelectConstruction(null);
      return;
    }
    // Стена выбранного этажа - выбор конструкции, всё остальное - выбор этажа.
    const wallId = hit.key === selectedKey ? hit.wallId : null;
    const target = wallId === null ? hit.key : `${hit.key}|${wallId}`;
    const now = performance.now();
    if (lastTap !== null && lastTap.target === target && now - lastTap.at < DOUBLE_TAP_MS) {
      lastTap = null;
      options.onOpenDetail(hit.key);
      return;
    }
    lastTap = { target, at: now };
    if (wallId === null) options.onSelect(hit.key);
    else options.onSelectConstruction(wallId);
  };
  const onCancel = (): void => {
    down = null;
  };
  const onLeave = (): void => {
    hoverPoint = null;
    setHoverWall(null);
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
      wallIndex = new Map();
      hoverWallId = null;
      labels.set(nextPlan?.labels ?? []);
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
        for (const wall of spec.walls) wallIndex.set(`${spec.key}|${wall.id}`, { spec, wall });
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
    setStyle: (nextSelected, nextHover, nextConstruction = null) => {
      selectedKey = nextSelected;
      hoverKey = nextHover;
      constructionId = nextSelected === null ? null : nextConstruction;
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
      labels.dispose();
      dom.removeEventListener('pointerdown', onDown);
      dom.removeEventListener('pointermove', onMove);
      dom.removeEventListener('pointerup', onUp);
      dom.removeEventListener('pointercancel', onCancel);
      dom.removeEventListener('pointerleave', onLeave);
      pivotOrbit.dispose();
      controls.dispose();
      disposeFloors();
      renderer.dispose();
      renderer.forceContextLoss();
      dom.remove();
    },
  };
};
