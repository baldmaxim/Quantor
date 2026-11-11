import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

import type { IFloor3dHighlight } from './floor3d-geometry';
import {
  midpoint,
  snapToNearestVertex,
  type IScreenPoint,
  type SceneVec3,
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
  setHighlight: (target: IFloor3dHighlight | null) => void;
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
}

export interface IFloor3dMeasureState {
  /** Одна точка - маркер, две - отрезок. */
  readonly points: readonly SceneVec3[];
  /** Середина отрезка на экране; `null` - отрезка нет или он за камерой. */
  readonly mid: IScreenPoint | null;
}

const FOV_DEG = 45;
/** Порог, после которого нажатие считается перетаскиванием, px. */
const CLICK_SLOP_PX = 6;
/** Сверху камера чуть смещена к югу: ось «вверх по экрану» = север плана, без вырождения. */
const TOP_DIRECTION = new THREE.Vector3(0, 1, 0.012).normalize();
const ISO_DIRECTION = new THREE.Vector3(0.8, 0.75, 1).normalize();

export const createFloor3dEngine = (
  host: HTMLElement,
  options: IFloor3dEngineOptions,
): IFloor3dEngine => {
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
  let highlight: IFloor3dHighlight | null = null;

  // Замер: маркеры и линия лежат в сцене отдельно от модели, поверх всего (depthTest выключен).
  let measuring = false;
  let points: SceneVec3[] = [];
  let lastMid: IScreenPoint | null = null;
  const measureGroup = new THREE.Group();
  measureGroup.renderOrder = 20;
  scene.add(measureGroup);
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
  const emitMeasure = (force: boolean): void => {
    if (!measuring || points.length === 0) {
      if (force) options.onMeasure(null);
      return;
    }
    const a = points[0] as SceneVec3;
    const b = points[1];
    const mid = b === undefined ? null : toScreen(midpoint(a, b));
    const moved =
      (mid === null) !== (lastMid === null) ||
      (mid !== null && lastMid !== null && Math.hypot(mid.x - lastMid.x, mid.y - lastMid.y) > 0.5);
    if (!force && !moved) return;
    lastMid = mid;
    options.onMeasure({ points: [...points], mid });
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
    ndc.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(ndc, camera);
    const anchor = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    if (measuring) {
      addMeasurePoint(anchor);
      return;
    }
    for (const hit of raycaster.intersectObjects([...model.pickables], false)) {
      const pick = pickOf(hit.object, hit.faceIndex);
      if (pick !== null) {
        options.onPick(pick, anchor);
        return;
      }
    }
    options.onPick(null, anchor);
  };
  // Точка замера: попадание луча в видимую призму; ближайшая вершина треугольника в 12 px - привязка.
  const addMeasurePoint = (anchor: IScreenPoint): void => {
    if (model === null) return;
    const prisms = model.pickables.filter((mesh) => (mesh.userData.pick as IFloor3dPickData).kind === 'prism');
    const hit = raycaster.intersectObjects(prisms, false)[0];
    if (hit === undefined) return;
    const position = hit.object instanceof THREE.Mesh ? hit.object.geometry.getAttribute('position') : null;
    const vertices: SceneVec3[] = [];
    if (hit.face && position) {
      for (const index of [hit.face.a, hit.face.b, hit.face.c]) {
        const vertex = new THREE.Vector3().fromBufferAttribute(position, index).applyMatrix4(hit.object.matrixWorld);
        vertices.push([vertex.x, vertex.y, vertex.z]);
      }
    }
    const { point } = snapToNearestVertex([hit.point.x, hit.point.y, hit.point.z], vertices, anchor, toScreen);
    points = points.length >= 2 ? [point] : [...points, point];
    redrawMeasure();
    lastMid = null;
    emitMeasure(true);
    requestRender();
  };
  dom.addEventListener('pointerdown', onDown);
  dom.addEventListener('pointerup', onUp);

  return {
    setModel: (next) => {
      if (model !== null) {
        scene.remove(model.group);
        model.dispose();
      }
      model = next;
      if (next !== null) next.setHighlight(highlight);
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
    setHighlight: (target) => {
      highlight = target;
      model?.setHighlight(target);
      requestRender();
    },
    setMeasuring: (on) => {
      if (measuring === on) return;
      measuring = on;
      if (!on) {
        points = [];
        lastMid = null;
        clearMeasureObjects();
        options.onMeasure(null);
        requestRender();
      }
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
