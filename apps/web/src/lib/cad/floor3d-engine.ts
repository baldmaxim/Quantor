import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

import { pickOf, type IFloor3dPick, type IFloor3dScene } from './floor3d-scene';

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
  dispose: () => void;
}

export interface IFloor3dEngineOptions {
  readonly reducedMotion: boolean;
  /** Щелчок (не перетаскивание): элемент под курсором или `null`; точка - от угла холста. */
  readonly onPick: (pick: IFloor3dPick | null, anchor: { x: number; y: number }) => void;
  /** Камера пошла двигаться: карточка у курсора устарела. */
  readonly onMove: () => void;
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
    for (const hit of raycaster.intersectObjects([...model.pickables], false)) {
      const pick = pickOf(hit.object, hit.faceIndex);
      if (pick !== null) {
        options.onPick(pick, anchor);
        return;
      }
    }
    options.onPick(null, anchor);
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
