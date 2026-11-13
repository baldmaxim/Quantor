import * as THREE from 'three';
import type { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

/**
 * Вращение вокруг точки модели под курсором (как в Navisworks) - по Shift + ЛКМ или Shift + средней
 * кнопке. Обычное вращение, панорама (ПКМ) и касание остаются за `OrbitControls` (зум - к курсору); на
 * время Shift-перетаскивания он отключается, азимут и возвышение применяются здесь: камера и цель
 * поворачиваются одним жёстким поворотом вокруг выбранной точки. Только слушатели DOM, состояния React нет.
 */

const WORLD_UP = new THREE.Vector3(0, 1, 0);
const EPS_POLAR = 0.01;
const MARKER_SCALE = 0.006;

/**
 * Жёсткий поворот камеры и цели вокруг `pivot`: азимут - вокруг мировой оси Y, затем изменение полярного угла
 * (с ограничением). Входные векторы не меняются.
 */
export const orbitAroundPivot = (
  cameraPos: THREE.Vector3,
  target: THREE.Vector3,
  pivot: THREE.Vector3,
  dAzimuth: number,
  dPolar: number,
  minPolar: number,
  maxPolar: number,
): { cameraPos: THREE.Vector3; target: THREE.Vector3 } => {
  let cam = cameraPos.clone();
  let tgt = target.clone();

  const rotate = (axis: THREE.Vector3, angle: number): void => {
    cam = cam.sub(pivot).applyAxisAngle(axis, angle).add(pivot);
    tgt = tgt.sub(pivot).applyAxisAngle(axis, angle).add(pivot);
  };

  if (dAzimuth !== 0) rotate(WORLD_UP, dAzimuth);

  const offset = cam.clone().sub(tgt);
  const length = offset.length();
  if (length > 1e-9 && dPolar !== 0) {
    const phi = Math.acos(THREE.MathUtils.clamp(offset.y / length, -1, 1));
    const next = THREE.MathUtils.clamp(phi + dPolar, minPolar, maxPolar);
    const delta = next - phi;
    const axis = new THREE.Vector3().crossVectors(WORLD_UP, offset);
    if (delta !== 0 && axis.lengthSq() > 1e-12) rotate(axis.normalize(), delta);
  }
  return { cameraPos: cam, target: tgt };
};

export interface IPivotOrbitOptions {
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  dom: HTMLElement;
  /** Сцена для маркера точки вращения. */
  scene: THREE.Scene;
  /** Мировая точка модели под курсором или `null`, если там пусто. */
  pickPoint: (clientX: number, clientY: number) => THREE.Vector3 | null;
  markerColor: () => THREE.ColorRepresentation;
  /** Запросить перерисовку. */
  onChange: () => void;
}

export const attachPivotOrbit = (options: IPivotOrbitOptions): { dispose: () => void } => {
  const { camera, controls, dom, scene, pickPoint, markerColor, onChange } = options;
  controls.zoomToCursor = true;

  const markerMaterial = new THREE.MeshBasicMaterial({
    color: markerColor(),
    depthTest: false,
    transparent: true,
    opacity: 0.9,
  });
  const markerGeometry = new THREE.SphereGeometry(1, 16, 12);
  const marker = new THREE.Mesh(markerGeometry, markerMaterial);
  marker.renderOrder = 999;
  marker.visible = false;
  scene.add(marker);

  let rotating = false;
  let activeId = -1;
  let pivot = new THREE.Vector3();
  let last = { x: 0, y: 0 };

  const placeMarker = (): void => {
    marker.position.copy(pivot);
    marker.scale.setScalar(Math.max(1e-4, camera.position.distanceTo(pivot) * MARKER_SCALE));
  };

  const stop = (): void => {
    if (!rotating) return;
    rotating = false;
    controls.enabled = true;
    marker.visible = false;
    onChange();
  };

  // Shift + ЛКМ или Shift + средняя кнопка. Слушатель - в фазе захвата, чтобы `controls.enabled = false`
  // успело выставиться до обработчика OrbitControls (иначе он начнёт панораму по Shift).
  const onDown = (event: PointerEvent): void => {
    if (rotating) return;
    if (event.pointerType !== 'mouse' || !event.shiftKey || (event.button !== 0 && event.button !== 1)) return;
    const picked = pickPoint(event.clientX, event.clientY);
    pivot = picked ?? controls.target.clone();
    markerMaterial.color.set(markerColor());
    rotating = true;
    activeId = event.pointerId;
    controls.enabled = false;
    last = { x: event.clientX, y: event.clientY };
    try {
      dom.setPointerCapture(event.pointerId);
    } catch {
      // Захват недоступен (указатель уже снят) - вращение продолжится без него.
    }
    if (picked !== null) {
      placeMarker();
      marker.visible = true;
      onChange();
    }
  };

  const onMove = (event: PointerEvent): void => {
    if (!rotating || event.pointerId !== activeId) return;
    const dx = event.clientX - last.x;
    const dy = event.clientY - last.y;
    last = { x: event.clientX, y: event.clientY };
    if (dx === 0 && dy === 0) return;
    const height = Math.max(1, dom.clientHeight);
    const result = orbitAroundPivot(
      camera.position,
      controls.target,
      pivot,
      (-2 * Math.PI * dx) / height,
      (-2 * Math.PI * dy) / height,
      Math.max(EPS_POLAR, controls.minPolarAngle),
      Math.min(controls.maxPolarAngle, Math.PI - EPS_POLAR),
    );
    camera.position.copy(result.cameraPos);
    controls.target.copy(result.target);
    if (marker.visible) placeMarker();
    controls.update();
    onChange();
  };

  const onEnd = (event: PointerEvent): void => {
    if (event.pointerId === activeId) stop();
  };

  dom.addEventListener('pointerdown', onDown, true);
  dom.addEventListener('pointermove', onMove);
  dom.addEventListener('pointerup', onEnd);
  dom.addEventListener('pointercancel', onEnd);
  dom.addEventListener('lostpointercapture', onEnd);

  return {
    dispose: () => {
      dom.removeEventListener('pointerdown', onDown, true);
      dom.removeEventListener('pointermove', onMove);
      dom.removeEventListener('pointerup', onEnd);
      dom.removeEventListener('pointercancel', onEnd);
      dom.removeEventListener('lostpointercapture', onEnd);
      stop();
      scene.remove(marker);
      markerGeometry.dispose();
      markerMaterial.dispose();
    },
  };
};
