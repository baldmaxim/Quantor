import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

import type { IFloor3dHighlight } from './floor3d-geometry';
import type { CadLayerCategory } from './layer-categories';
import {
  buildFeatureEdges,
  midpoint,
  snapPoint,
  type IFeatureEdges,
  type IScreenPoint,
  type ISnapResult,
  type SceneVec3,
  type SnapKind,
  type Triangle3,
} from './floor3d-measure';
import {
  pickOf,
  readFloor3dColors,
  type IFloor3dPick,
  type IFloor3dPickData,
  type IFloor3dScene,
} from './floor3d-scene';

/**
 * Рендер 3D-вида этажа (ADR-0039): renderer, камера и орбитальное управление мышью и касанием.
 *
 * Рисование по требованию: кадр строится при изменении камеры, размера или модели, постоянного
 * цикла нет. При `prefers-reduced-motion` инерции (damping) нет. Свет - ambient и directional, без
 * теней. Все ресурсы освобождаются в `dispose`.
 */

export type Floor3dViewKind = 'top' | 'iso';

export interface IFloor3dEngine {
  /** Показать модель: прежняя освобождается. Камера вписывается только при первой непустой модели. */
  setModel: (scene: IFloor3dScene | null) => void;
  setView: (kind: Floor3dViewKind) => void;
  fit: () => void;
  /** Выделить элемент оверлеем; `null` - снять. Переживает пересборку модели только через повторный вызов. */
  setHighlight: (targets: readonly IFloor3dHighlight[]) => void;
  /** Показать или скрыть категорию без пересборки сцены; переживает пересборку модели. */
  setCategoryVisible: (category: CadLayerCategory, visible: boolean) => void;
  /** Режим измерения: клики ставят точки, а не выбирают элемент; выход очищает замер. */
  setMeasuring: (on: boolean) => void;
  dispose: () => void;
}

export interface IFloor3dEngineOptions {
  readonly reducedMotion: boolean;
  /** Щелчок (не перетаскивание): элемент под курсором или `null`; точка - от угла холста. */
  readonly onPick: (pick: IFloor3dPick | null, anchor: { x: number; y: number }) => void;
  /** Камера пошла двигаться: карточка у курсора устарела. */
  readonly onMove: () => void;
  /** Состояние замера: точки сцены и экранная точка середины отрезка (px от угла холста); `null` - замера нет. */
  readonly onMeasure: (state: IFloor3dMeasureState | null) => void;
  /** Привязка под курсором (мышь, режим измерения): вид и экранная точка; `null` - привязки нет. */
  readonly onSnap: (state: IFloor3dSnapState | null) => void;
}

export interface IFloor3dSnapState {
  readonly kind: SnapKind;
  /** Точка привязки на экране, px от угла холста. */
  readonly at: IScreenPoint;
}

export interface IFloor3dMeasureState {
  /** Одна точка - маркер, две - отрезок. */
  readonly points: readonly SceneVec3[];
  /** Середина отрезка на экране; `null` - отрезка нет или он за камерой. */
  readonly mid: IScreenPoint | null;
  /** Вторая точка - «резинка» к точке привязки под курсором, а не поставленная. */
  readonly live: boolean;
}

const FOV_DEG = 45;
/** Порог, после которого нажатие считается перетаскиванием, px. */
const CLICK_SLOP_PX = 6;
/** Сверху камера чуть смещена к югу: ось «вверх по экрану» = север плана, без вырождения. */
export const TOP_DIRECTION = new THREE.Vector3(0, 1, 0.012).normalize();
/**
 * Изометрия «как на листе»: камера с юга (+Z сцены), наклон ~50 градусов; север плана (-Z) - вверх
 * экрана, восток (+X) - вправо, без зеркала.
 */
export const ISO_DIRECTION = new THREE.Vector3(0, 1.2, 1).normalize();

const MARKER_PX = { vertex: 14, edge: 14, face: 9 } as const;
const MARKER_TEXTURE_PX = 32;

/** Белая маска маркера: угол - квадрат, ребро - ромб, грань - круг; цвет задаёт материал. */
const markerTexture = (kind: SnapKind): THREE.CanvasTexture | null => {
  const canvas = document.createElement('canvas');
  canvas.width = MARKER_TEXTURE_PX;
  canvas.height = MARKER_TEXTURE_PX;
  const context = canvas.getContext('2d');
  if (context === null) return null;
  const c = MARKER_TEXTURE_PX / 2;
  context.fillStyle = 'white';
  context.beginPath();
  if (kind === 'vertex') context.rect(4, 4, MARKER_TEXTURE_PX - 8, MARKER_TEXTURE_PX - 8);
  else if (kind === 'edge') {
    context.moveTo(c, 1);
    context.lineTo(MARKER_TEXTURE_PX - 1, c);
    context.lineTo(c, MARKER_TEXTURE_PX - 1);
    context.lineTo(1, c);
    context.closePath();
  } else context.arc(c, c, c - 6, 0, Math.PI * 2);
  context.fill();
  return new THREE.CanvasTexture(canvas);
};

export const createFloor3dEngine = (
  host: HTMLElement,
  options: IFloor3dEngineOptions,
): IFloor3dEngine => {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x000000, 0);
  const dom = renderer.domElement;
  dom.className = 'block h-full w-full touch-none';
  const cursorClass = 'cursor-crosshair';
  host.appendChild(dom);

  const scene = new THREE.Scene();
  scene.add(new THREE.AmbientLight(0xffffff, 1.5));
  const sun = new THREE.DirectionalLight(0xffffff, 2);
  sun.position.set(1, 2, 1.5);
  scene.add(sun);

  const camera = new THREE.PerspectiveCamera(FOV_DEG, 1, 0.1, 1000);
  const controls = new OrbitControls(camera, dom);
  controls.enableDamping = !options.reducedMotion;
  controls.screenSpacePanning = true;

  let disposed = false;
  let frame = 0;
  const render = (): void => {
    frame = 0;
    if (disposed) return;
    const moving = controls.update();
    renderer.render(scene, camera);
    emitMeasure(false);
    if (moving) requestRender();
  };
  function requestRender(): void {
    if (disposed || frame !== 0) return;
    frame = requestAnimationFrame(render);
  }
  controls.addEventListener('change', requestRender);
  controls.addEventListener('start', options.onMove);

  let model: IFloor3dScene | null = null;
  let fitted = false;
  let highlight: readonly IFloor3dHighlight[] = [];
  const hiddenCategories = new Set<CadLayerCategory>();

  // Замер: маркеры и линия лежат в сцене отдельно от модели, поверх всего (depthTest выключен).
  let measuring = false;
  let points: SceneVec3[] = [];
  let lastMid: IScreenPoint | null = null;
  const measureGroup = new THREE.Group();
  measureGroup.renderOrder = 20;
  scene.add(measureGroup);
  const hoverGroup = new THREE.Group();
  scene.add(hoverGroup);
  const clearMeasureObjects = (): void => {
    for (const child of [...measureGroup.children]) {
      measureGroup.remove(child);
      const item = child as THREE.Object3D & { geometry?: THREE.BufferGeometry; material?: THREE.Material };
      item.geometry?.dispose();
      item.material?.dispose();
    }
  };
  const toScreen = (point: SceneVec3): IScreenPoint | null => {
    const projected = new THREE.Vector3(point[0], point[1], point[2]).project(camera);
    if (projected.z > 1 || projected.z < -1) return null;
    return {
      x: ((projected.x + 1) / 2) * Math.max(1, dom.clientWidth),
      y: ((1 - projected.y) / 2) * Math.max(1, dom.clientHeight),
    };
  };
  // Привязка под курсором (мышь): маркер и «резинка» от первой точки.
  let hover: ISnapResult | null = null;
  let hoverAccent = new THREE.Color(readFloor3dColors().accent);
  const shown = (): { readonly pts: readonly SceneVec3[]; readonly live: boolean } =>
    points.length === 1 && hover !== null
      ? { pts: [points[0] as SceneVec3, hover.point], live: true }
      : { pts: points, live: false };
  const emitMeasure = (force: boolean): void => {
    const { pts, live } = shown();
    if (!measuring || pts.length === 0) {
      if (force) options.onMeasure(null);
      return;
    }
    const a = pts[0] as SceneVec3;
    const b = pts[1];
    const mid = b === undefined ? null : toScreen(midpoint(a, b));
    const moved =
      (mid === null) !== (lastMid === null) ||
      (mid !== null && lastMid !== null && Math.hypot(mid.x - lastMid.x, mid.y - lastMid.y) > 0.5);
    if (!force && !moved) return;
    lastMid = mid;
    options.onMeasure({ points: [...pts], mid, live });
  };
  const redrawMeasure = (): void => {
    clearMeasureObjects();
    if (points.length === 0) return;
    const accent = new THREE.Color(readFloor3dColors().accent);
    const positions = points.map((point) => new THREE.Vector3(point[0], point[1], point[2]));
    const dots = new THREE.Points(
      new THREE.BufferGeometry().setFromPoints(positions),
      new THREE.PointsMaterial({ color: accent, size: 10, sizeAttenuation: false, depthTest: false }),
    );
    dots.renderOrder = 20;
    measureGroup.add(dots);
    if (positions.length === 2) {
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(positions),
        new THREE.LineBasicMaterial({ color: accent, depthTest: false }),
      );
      line.renderOrder = 20;
      measureGroup.add(line);
    }
  };

  const place = (direction: THREE.Vector3): void => {
    if (model === null) return;
    const box = new THREE.Box3().setFromObject(model.group);
    if (box.isEmpty()) return;
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const radius = Math.max(sphere.radius, 0.1);
    const distance = (radius / Math.sin(THREE.MathUtils.degToRad(FOV_DEG) / 2)) * 1.05;
    camera.near = Math.max(0.01, distance * 0.01);
    camera.far = (distance + radius) * 10;
    camera.updateProjectionMatrix();
    controls.minDistance = radius * 0.05;
    controls.maxDistance = distance * 6;
    controls.target.copy(sphere.center);
    camera.position.copy(sphere.center).addScaledVector(direction, distance);
    camera.lookAt(sphere.center);
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

  // Щелчок отличается от перетаскивания смещением указателя.
  let down: { x: number; y: number } | null = null;
  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  const onDown = (event: PointerEvent): void => {
    down = { x: event.clientX, y: event.clientY };
  };
  const onUp = (event: PointerEvent): void => {
    const start = down;
    down = null;
    if (start === null || model === null) return;
    if (Math.hypot(event.clientX - start.x, event.clientY - start.y) > CLICK_SLOP_PX) return;
    const rect = dom.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    if (measuring) {
      addMeasurePoint(event.clientX, event.clientY);
      return;
    }
    ndc.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(ndc, camera);
    const anchor = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    // Скрытое категорией в клик не входит: Raycaster флаг visible не проверяет.
    for (const hit of raycaster.intersectObjects(model.pickables.filter((mesh) => mesh.visible), false)) {
      const pick = pickOf(hit.object, hit.faceIndex);
      if (pick !== null) {
        options.onPick(pick, anchor);
        return;
      }
    }
    options.onPick(null, anchor);
  };
  // Рёбра сетки считаются один раз на меш при первом наведении: модель пересобрана - меши новые.
  const featureCache = new WeakMap<THREE.Mesh, IFeatureEdges>();
  const featureEdgesOf = (mesh: THREE.Mesh): IFeatureEdges => {
    const cached = featureCache.get(mesh);
    if (cached !== undefined) return cached;
    const geometry = mesh.geometry;
    const built = buildFeatureEdges(geometry.getAttribute('position').array, geometry.index?.array ?? null);
    featureCache.set(mesh, built);
    return built;
  };

  // Точка под курсором: попадание луча в видимую призму и привязка угол -> ребро -> грань.
  // Меши модели лежат без преобразований, поэтому вершины берутся в мировых координатах напрямую.
  const snapAt = (clientX: number, clientY: number): ISnapResult | null => {
    if (model === null) return null;
    const rect = dom.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return null;
    ndc.set(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(ndc, camera);
    const prisms = model.pickables.filter(
      (mesh) => mesh.visible && (mesh.userData.pick as IFloor3dPickData).kind === 'prism',
    );
    const hit = raycaster.intersectObjects(prisms, false)[0];
    if (hit === undefined || !(hit.object instanceof THREE.Mesh) || !hit.face) return null;
    const position = hit.object.geometry.getAttribute('position');
    const vertex = (index: number): SceneVec3 => {
      const v = new THREE.Vector3().fromBufferAttribute(position, index).applyMatrix4(hit.object.matrixWorld);
      return [v.x, v.y, v.z];
    };
    const triangle: Triangle3 = [vertex(hit.face.a), vertex(hit.face.b), vertex(hit.face.c)];
    const triangleIndex = hit.faceIndex ?? -1;
    const features = featureEdgesOf(hit.object);
    const flags: readonly [boolean, boolean, boolean] =
      triangleIndex < 0
        ? [false, false, false]
        : [
            features.isFeature(triangleIndex, 0),
            features.isFeature(triangleIndex, 1),
            features.isFeature(triangleIndex, 2),
          ];
    return snapPoint(
      [hit.point.x, hit.point.y, hit.point.z],
      triangle,
      flags,
      { x: clientX - rect.left, y: clientY - rect.top },
      toScreen,
    );
  };

  // Объекты превью (маркер по виду привязки и пунктир «резинки») создаются при первом наведении.
  interface IHoverObjects {
    readonly markers: Record<SnapKind, THREE.Points>;
    readonly rubber: THREE.Line;
    readonly rubberMaterial: THREE.LineDashedMaterial;
    readonly textures: THREE.Texture[];
  }
  let hoverObjects: IHoverObjects | null = null;
  const ensureHoverObjects = (): IHoverObjects => {
    if (hoverObjects !== null) return hoverObjects;
    const textures: THREE.Texture[] = [];
    const marker = (kind: SnapKind): THREE.Points => {
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(3), 3));
      const map = markerTexture(kind);
      if (map !== null) textures.push(map);
      const material = new THREE.PointsMaterial({
        color: hoverAccent,
        size: MARKER_PX[kind],
        sizeAttenuation: false,
        depthTest: false,
        transparent: true,
        alphaTest: 0.5,
        ...(map === null ? {} : { map }),
      });
      const points3 = new THREE.Points(geometry, material);
      points3.renderOrder = 22;
      points3.frustumCulled = false;
      points3.visible = false;
      return points3;
    };
    const markers = { vertex: marker('vertex'), edge: marker('edge'), face: marker('face') };
    const rubberGeometry = new THREE.BufferGeometry();
    rubberGeometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
    const rubberMaterial = new THREE.LineDashedMaterial({ color: hoverAccent, dashSize: 0.1, gapSize: 0.06, depthTest: false });
    const rubber = new THREE.Line(rubberGeometry, rubberMaterial);
    rubber.renderOrder = 21;
    rubber.frustumCulled = false;
    rubber.visible = false;
    hoverGroup.add(markers.vertex, markers.edge, markers.face, rubber);
    hoverObjects = { markers, rubber, rubberMaterial, textures };
    return hoverObjects;
  };
  const disposeHoverObjects = (): void => {
    if (hoverObjects === null) return;
    for (const child of [...hoverGroup.children]) {
      hoverGroup.remove(child);
      const item = child as THREE.Object3D & { geometry?: THREE.BufferGeometry; material?: THREE.Material };
      item.geometry?.dispose();
      item.material?.dispose();
    }
    for (const texture of hoverObjects.textures) texture.dispose();
    hoverObjects = null;
  };
  // «Резинка» тянется от первой точки к привязке, пока вторая не поставлена.
  const syncRubber = (): void => {
    const objects = hoverObjects;
    if (objects === null) return;
    const first = points[0];
    const live = points.length === 1 && hover !== null && first !== undefined;
    objects.rubber.visible = live;
    if (!live || hover === null || first === undefined) return;
    const attribute = objects.rubber.geometry.getAttribute('position') as THREE.BufferAttribute;
    attribute.setXYZ(0, first[0], first[1], first[2]);
    attribute.setXYZ(1, hover.point[0], hover.point[1], hover.point[2]);
    attribute.needsUpdate = true;
    objects.rubber.computeLineDistances();
    const distance = camera.position.distanceTo(controls.target);
    objects.rubberMaterial.dashSize = distance * 0.012;
    objects.rubberMaterial.gapSize = distance * 0.008;
  };
  let snapEmitted = false;
  const setHover = (next: ISnapResult | null): void => {
    if (next === null && hover === null && !snapEmitted) return;
    hover = next;
    const objects = ensureHoverObjects();
    for (const kind of ['vertex', 'edge', 'face'] as const) {
      const marker = objects.markers[kind];
      marker.visible = next !== null && next.kind === kind;
      if (next !== null && marker.visible) {
        const attribute = marker.geometry.getAttribute('position') as THREE.BufferAttribute;
        attribute.setXYZ(0, next.point[0], next.point[1], next.point[2]);
        attribute.needsUpdate = true;
      }
    }
    syncRubber();
    const at = next === null ? null : toScreen(next.point);
    snapEmitted = next !== null && at !== null;
    options.onSnap(next !== null && at !== null ? { kind: next.kind, at } : null);
    emitMeasure(true);
    requestRender();
  };

  // Наведение: не чаще раза за кадр; на касании превью нет, перетаскивание камеры его прячет.
  let moveFrame = 0;
  let lastMove: { x: number; y: number } | null = null;
  const cancelMoveFrame = (): void => {
    if (moveFrame !== 0) cancelAnimationFrame(moveFrame);
    moveFrame = 0;
    lastMove = null;
  };
  const onHoverMove = (event: PointerEvent): void => {
    if (!measuring) return;
    if (event.pointerType === 'touch' || event.buttons !== 0) {
      cancelMoveFrame();
      setHover(null);
      return;
    }
    lastMove = { x: event.clientX, y: event.clientY };
    if (moveFrame !== 0) return;
    moveFrame = requestAnimationFrame(() => {
      moveFrame = 0;
      const at = lastMove;
      if (disposed || !measuring || at === null) return;
      setHover(snapAt(at.x, at.y));
    });
  };
  const clearHover = (): void => {
    cancelMoveFrame();
    setHover(null);
  };
  const addMeasurePoint = (clientX: number, clientY: number): void => {
    const snap = snapAt(clientX, clientY);
    if (snap === null) return;
    points = points.length >= 2 ? [snap.point] : [...points, snap.point];
    redrawMeasure();
    lastMid = null;
    syncRubber();
    emitMeasure(true);
    requestRender();
  };
  dom.addEventListener('pointerdown', onDown);
  dom.addEventListener('pointerup', onUp);
  dom.addEventListener('pointermove', onHoverMove);
  dom.addEventListener('pointerleave', clearHover);
  controls.addEventListener('start', clearHover);

  return {
    setModel: (next) => {
      if (model !== null) {
        scene.remove(model.group);
        model.dispose();
      }
      model = next;
      if (next !== null) {
        next.setHighlight(highlight);
        for (const category of hiddenCategories) next.setCategoryVisible(category, false);
      }
      if (next === null) {
        requestRender();
        return;
      }
      scene.add(next.group);
      if (!fitted) {
        fitted = true;
        place(ISO_DIRECTION);
      } else requestRender();
    },
    setHighlight: (targets) => {
      highlight = targets;
      model?.setHighlight(targets);
      requestRender();
    },
    setCategoryVisible: (category, visible) => {
      if (visible) hiddenCategories.delete(category);
      else hiddenCategories.add(category);
      model?.setCategoryVisible(category, visible);
      requestRender();
    },
    setMeasuring: (on) => {
      if (measuring === on) return;
      measuring = on;
      dom.classList.toggle(cursorClass, on);
      if (on) {
        hoverAccent = new THREE.Color(readFloor3dColors().accent);
        return;
      }
      clearHover();
      points = [];
      lastMid = null;
      clearMeasureObjects();
      options.onMeasure(null);
      requestRender();
    },
    setView: (kind) => place(kind === 'top' ? TOP_DIRECTION : ISO_DIRECTION),
    fit: () => {
      // Вписать - с тем же направлением, с которого сейчас смотрит камера.
      const direction = camera.position.clone().sub(controls.target);
      place(direction.lengthSq() > 0 ? direction.normalize() : ISO_DIRECTION);
    },
    dispose: () => {
      disposed = true;
      if (frame !== 0) cancelAnimationFrame(frame);
      observer.disconnect();
      dom.removeEventListener('pointerdown', onDown);
      dom.removeEventListener('pointerup', onUp);
      dom.removeEventListener('pointermove', onHoverMove);
      dom.removeEventListener('pointerleave', clearHover);
      controls.removeEventListener('start', clearHover);
      cancelMoveFrame();
      disposeHoverObjects();
      scene.remove(hoverGroup);
      controls.removeEventListener('change', requestRender);
      controls.removeEventListener('start', options.onMove);
      controls.dispose();
      clearMeasureObjects();
      scene.remove(measureGroup);
      if (model !== null) {
        scene.remove(model.group);
        model.dispose();
        model = null;
      }
      renderer.dispose();
      renderer.forceContextLoss();
      dom.remove();
    },
  };
};
