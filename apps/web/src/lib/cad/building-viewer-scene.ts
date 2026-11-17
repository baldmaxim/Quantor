import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

import { explodeOffsets, fitDistance, viewerBounds, type IViewerPlan } from './building-viewer-geometry';
import { buildFloor, type IFloorEntry } from './building-viewer-floor';
import { readBuildingViewerColors, type IBuildingViewerColors } from './building-viewer-colors';
import { createGroupLabels } from './building-viewer-labels';
import { attachPivotOrbit } from './pivot-orbit';

/**
 * Рендер просмотрщика объекта: перспективная камера и `OrbitControls` вокруг здания из настоящих
 * стен всех этажей. Кадр строится по требованию (смена камеры, размера, стиля, модели), постоянного
 * цикла нет; инерция - только пока идёт движение и если не включён `prefers-reduced-motion`.
 * Все ресурсы освобождаются в `dispose`. Модуль грузится вместе с просмотрщиком: `three` не попадает
 * в чанк страницы.
 *
 * Выбор - только этаж целиком: щелчок по другому этажу выбирает его, по уже выбранному или в пустоту -
 * снимает выбор. Конструкции выбираются в детальном 3D этажа.
 */

export interface IBuildingViewerOptions {
  readonly reducedMotion: boolean;
  /** Наведение (только мышь): ключ этажа или `null`; точка - от угла холста. */
  readonly onHover: (key: string | null, anchor: { x: number; y: number } | null) => void;
  /**
   * Щелчок или касание (не перетаскивание): ключ другого этажа - выбрать его; `null` - выбор снят
   * повторным щелчком по выбранному этажу или щелчком в пустоту.
   */
  readonly onSelect: (key: string | null) => void;
  /** Двойной щелчок или двойное касание по этажу. */
  readonly onOpenDetail: (key: string) => void;
}

export interface IBuildingViewer {
  /** Показать модель; прежняя освобождается. Камера вписывается, когда набор этажей сменился. */
  setPlan: (plan: IViewerPlan | null, colors: IBuildingViewerColors) => void;
  /** Новые цвета темы без пересборки модели и без сдвига камеры. */
  setColors: (colors: IBuildingViewerColors) => void;
  /** Выбранный этаж (акцент) и наведённый (подсветка); остальные этажи при выборе приглушаются. */
  setStyle: (selectedKey: string | null, hoverKey: string | null) => void;
  setExploded: (exploded: boolean) => void;
  /**
   * Группы расчётов TENDER по ключу этажа (ADR-0051): становятся дочерними группе этажа и двигаются с ним
   * при разнесении; владелец групп освобождает их сам. `null` - слоя нет.
   */
  setCalcGroups: (groups: ReadonlyMap<string, THREE.Object3D> | null) => void;
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
/** Непрозрачность плит и стен здания, не поставленного на объект. */
const GHOST_OPACITY = 0.28;
/** Стекло окна с принятой высотой и стекло-кандидат (бледнее): как в 3D этажа. */
const GLASS_OPACITY = 0.5;
const GLASS_CANDIDATE_OPACITY = 0.22;
/** Доля белого в цвете подоконной части и перемычки относительно кладки: как в 3D этажа. */
const SILL_LIGHTEN = 0.4;
const WHITE = new THREE.Color('white');

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
  let exploded = false;
  let factor = 0;
  let anim: IExplodeAnim | null = null;
  let signature = '';
  let groundY = -Infinity;
  let calcGroups: ReadonlyMap<string, THREE.Object3D> | null = null;

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

  const attachCalc = (): void => {
    for (const entry of entries) {
      const group = calcGroups?.get(entry.key);
      if (group !== undefined) entry.group.add(group);
    }
  };

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
        const base = part === 'volume' ? colors.muted : part === 'sill' ? colors.masonry : colors[part === 'glassCandidate' ? 'glass' : part];
        scratch.set(base);
        if (part === 'sill') scratch.lerp(WHITE, SILL_LIGHTEN);
        if (selected) scratch.copy(accentColor);
        else if (hovered) scratch.lerp(accentColor, 0.55);
        mesh.material.color.copy(scratch);
        let opacity = part === 'glass' ? GLASS_OPACITY : part === 'glassCandidate' ? GLASS_CANDIDATE_OPACITY : 1;
        if (part === 'volume') opacity = selected ? 0.3 : hovered ? 0.35 : dimmed ? 0.05 : 0.12;
        else if (dimmed) opacity = Math.min(opacity, 0.3);
        // Здание не поставлено на объект: его место условное, поэтому оно полупрозрачное.
        if (entry.ghost && !selected && part !== 'volume') opacity = Math.min(opacity, hovered ? 0.6 : GHOST_OPACITY);
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
  const pickAt = (clientX: number, clientY: number): string | null => {
    const key: unknown = rayHit(clientX, clientY)?.object.userData.floorKey;
    return typeof key === 'string' ? key : null;
  };

  let down: { x: number; y: number; moved: boolean } | null = null;
  let lastTap: { target: string; at: number } | null = null;
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
    if (key === null) {
      // Щелчок в пустоту снимает выбор этажа.
      lastTap = null;
      if (selectedKey !== null) options.onSelect(null);
      return;
    }
    const now = performance.now();
    if (lastTap !== null && lastTap.target === key && now - lastTap.at < DOUBLE_TAP_MS) {
      lastTap = null;
      options.onOpenDetail(key);
      return;
    }
    lastTap = { target: key, at: now };
    // Повторный щелчок по уже выбранному этажу снимает выбор.
    options.onSelect(key === selectedKey ? null : key);
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
        pickTargets.push(...entry.meshes.values());
      }
      groundY = Math.min(...nextPlan.floors.map((spec) => spec.slabBottom));
      attachCalc();
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
    setCalcGroups: (next) => {
      for (const group of calcGroups?.values() ?? []) group.removeFromParent();
      calcGroups = next;
      attachCalc();
      requestRender();
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
