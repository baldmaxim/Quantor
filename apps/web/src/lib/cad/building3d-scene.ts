import * as THREE from 'three';

import type { IBuildingFloorSpec, IBuildingPlan } from './building3d-geometry';

/**
 * Рендер колонки «Здание»: ортографическая изометрия стопки этажей. Камера крутится вокруг
 * вертикали перетаскиванием (мышь и касание), угол места постоянный. Кадр строится по требованию
 * (смена камеры, размера, стиля или модели), постоянного цикла и анимации нет (reduced-motion учтён). Все ресурсы освобождаются
 * в `dispose`. Модуль грузится вместе с колонкой: `three` не попадает в общий чанк маршрута.
 */

export interface IBuilding3dColors {
  readonly accent: string;
  readonly muted: string;
  readonly border: string;
  readonly surface: string;
}

const FALLBACK_COLOR = 'gray';

export const readBuilding3dColors = (): IBuilding3dColors => {
  if (typeof document === 'undefined') {
    return { accent: FALLBACK_COLOR, muted: FALLBACK_COLOR, border: FALLBACK_COLOR, surface: FALLBACK_COLOR };
  }
  const style = getComputedStyle(document.documentElement);
  const token = (name: string): string => style.getPropertyValue(name).trim() || FALLBACK_COLOR;
  return {
    accent: token('--accent'),
    muted: token('--muted'),
    border: token('--border'),
    surface: token('--surface'),
  };
};

export interface IBuilding3dOptions {
  /** Наведение (только мышь): ключ этажа или `null`; точка - от угла холста. */
  readonly onHover: (key: string | null, anchor: { x: number; y: number } | null) => void;
  /** Щелчок или касание (не перетаскивание) по этажу. */
  readonly onSelect: (key: string) => void;
}

export interface IBuilding3dView {
  setPlan: (plan: IBuildingPlan | null, colors: IBuilding3dColors) => void;
  /** Текущий этаж (акцент) и наведённый (подсветка). */
  setHighlight: (currentKey: string | null, hoverKey: string | null) => void;
  dispose: () => void;
}

/** Порог, после которого нажатие считается перетаскиванием, px. */
const CLICK_SLOP_PX = 6;
const ROTATE_RAD_PER_PX = 0.01;
const START_AZIMUTH = Math.PI / 4;
/** Угол места изометрии: arctan(1 / sqrt(2)) ~ 35°. */
const ELEVATION = Math.atan(1 / Math.SQRT2);
const MARGIN = 1.1;

interface IFloorMeshes {
  readonly key: string;
  readonly slab: THREE.Mesh;
  readonly volume: THREE.Mesh;
  readonly edges: THREE.LineSegments;
}

const shapeOf = (spec: IBuildingFloorSpec): THREE.Shape =>
  new THREE.Shape(spec.shell.map(([u, v]) => new THREE.Vector2(u, v)));

/** Призма из контура: поворот на -90° вокруг X даёт `(u, высота, -v)`. */
const prism = (spec: IBuildingFloorSpec, yBottom: number, yTop: number): THREE.BufferGeometry | null => {
  const depth = yTop - yBottom;
  if (!(depth > 0)) return null;
  try {
    const geometry = new THREE.ExtrudeGeometry(shapeOf(spec), { depth, bevelEnabled: false, steps: 1 });
    geometry.rotateX(-Math.PI / 2);
    geometry.translate(0, yBottom, 0);
    return geometry.getAttribute('position').count > 0 ? geometry : null;
  } catch {
    // Самопересекающийся контур триангуляция не берёт: этаж пропускается, остальные строятся.
    return null;
  }
};

export const createBuilding3dView = (host: HTMLElement, options: IBuilding3dOptions): IBuilding3dView => {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x000000, 0);
  const dom = renderer.domElement;
  dom.className = 'block h-full w-full touch-none';
  host.appendChild(dom);

  const scene = new THREE.Scene();
  scene.add(new THREE.AmbientLight(0xffffff, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(1, 2, 1.5);
  scene.add(sun);

  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 100);
  let azimuth = START_AZIMUTH;
  let radius = 10;

  let disposed = false;
  let frame = 0;
  const render = (): void => {
    frame = 0;
    if (disposed) return;
    renderer.render(scene, camera);
  };
  const requestRender = (): void => {
    if (disposed || frame !== 0) return;
    frame = requestAnimationFrame(render);
  };

  const placeCamera = (): void => {
    const horizontal = Math.cos(ELEVATION) * radius * 3;
    camera.position.set(
      Math.sin(azimuth) * horizontal,
      Math.sin(ELEVATION) * radius * 3,
      Math.cos(azimuth) * horizontal,
    );
    camera.near = 0.1;
    camera.far = radius * 8;
    camera.lookAt(0, 0, 0);
    camera.updateMatrixWorld();
  };

  const fitFrustum = (): void => {
    const width = Math.max(1, host.clientWidth);
    const height = Math.max(1, host.clientHeight);
    const aspect = width / height;
    const half = radius * MARGIN;
    const halfHeight = aspect >= 1 ? half : half / aspect;
    camera.left = -halfHeight * aspect;
    camera.right = halfHeight * aspect;
    camera.top = halfHeight;
    camera.bottom = -halfHeight;
    camera.updateProjectionMatrix();
  };

  const resize = (): void => {
    renderer.setSize(Math.max(1, host.clientWidth), Math.max(1, host.clientHeight), false);
    fitFrustum();
    requestRender();
  };
  const observer = new ResizeObserver(resize);
  observer.observe(host);

  let group: THREE.Group | null = null;
  let floors: IFloorMeshes[] = [];
  let colors: IBuilding3dColors = readBuilding3dColors();
  let currentKey: string | null = null;
  let hoverKey: string | null = null;

  const disposeGroup = (): void => {
    if (group === null) return;
    scene.remove(group);
    group.traverse((object) => {
      if (object instanceof THREE.Mesh || object instanceof THREE.LineSegments) {
        object.geometry.dispose();
        const material = object.material;
        if (Array.isArray(material)) material.forEach((item) => item.dispose());
        else material.dispose();
      }
    });
    group = null;
    floors = [];
  };

  const applyStyle = (): void => {
    for (const item of floors) {
      const current = item.key === currentKey;
      const hovered = item.key === hoverKey;
      const tone = current || hovered ? colors.accent : colors.muted;
      const slab = item.slab.material as THREE.MeshLambertMaterial;
      const volume = item.volume.material as THREE.MeshLambertMaterial;
      const edges = item.edges.material as THREE.LineBasicMaterial;
      slab.color.set(tone);
      slab.opacity = current ? 1 : hovered ? 0.9 : 0.75;
      volume.color.set(tone);
      volume.opacity = current ? 0.3 : hovered ? 0.35 : 0.1;
      edges.color.set(current || hovered ? colors.accent : colors.border);
    }
    requestRender();
  };

  const pickTargets = (): THREE.Object3D[] => floors.flatMap((item) => [item.volume, item.slab]);
  const keyOfObject = (object: THREE.Object3D): string | null => {
    const key: unknown = object.userData.floorKey;
    return typeof key === 'string' ? key : null;
  };

  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  const pickAt = (clientX: number, clientY: number): string | null => {
    const rect = dom.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0 || floors.length === 0) return null;
    ndc.set(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(ndc, camera);
    const hit = raycaster.intersectObjects(pickTargets(), false)[0];
    return hit ? keyOfObject(hit.object) : null;
  };

  let down: { x: number; y: number; azimuth: number; moved: boolean } | null = null;
  const onDown = (event: PointerEvent): void => {
    down = { x: event.clientX, y: event.clientY, azimuth, moved: false };
    dom.setPointerCapture?.(event.pointerId);
  };
  const onMove = (event: PointerEvent): void => {
    const start = down;
    if (start !== null) {
      const dx = event.clientX - start.x;
      if (start.moved || Math.hypot(dx, event.clientY - start.y) > CLICK_SLOP_PX) {
        start.moved = true;
        azimuth = start.azimuth - dx * ROTATE_RAD_PER_PX;
        placeCamera();
        options.onHover(null, null);
        requestRender();
      }
      return;
    }
    if (event.pointerType === 'touch') return;
    const rect = dom.getBoundingClientRect();
    const key = pickAt(event.clientX, event.clientY);
    options.onHover(key, key === null ? null : { x: event.clientX - rect.left, y: event.clientY - rect.top });
  };
  const onUp = (event: PointerEvent): void => {
    const start = down;
    down = null;
    dom.releasePointerCapture?.(event.pointerId);
    if (start === null || start.moved) return;
    const key = pickAt(event.clientX, event.clientY);
    if (key !== null) options.onSelect(key);
  };
  const onCancel = (): void => {
    down = null;
  };
  const onLeave = (): void => options.onHover(null, null);
  dom.addEventListener('pointerdown', onDown);
  dom.addEventListener('pointermove', onMove);
  dom.addEventListener('pointerup', onUp);
  dom.addEventListener('pointercancel', onCancel);
  dom.addEventListener('pointerleave', onLeave);

  return {
    setPlan: (plan, nextColors) => {
      disposeGroup();
      colors = nextColors;
      if (plan === null) {
        requestRender();
        return;
      }
      const next = new THREE.Group();
      const built: IFloorMeshes[] = [];
      for (const spec of plan.floors) {
        const slabGeometry = prism(spec, spec.slabBottom, spec.slabTop);
        const volumeGeometry = prism(spec, spec.slabTop, spec.volumeTop);
        const geometry = slabGeometry ?? volumeGeometry;
        if (geometry === null) continue;
        const slab = new THREE.Mesh(
          slabGeometry ?? geometry,
          new THREE.MeshLambertMaterial({ transparent: true }),
        );
        const volume = new THREE.Mesh(
          volumeGeometry ?? geometry,
          new THREE.MeshLambertMaterial({ transparent: true, depthWrite: false }),
        );
        if (slabGeometry === null) slab.visible = false;
        if (volumeGeometry === null) volume.visible = false;
        slab.userData.floorKey = spec.key;
        volume.userData.floorKey = spec.key;
        const edges = new THREE.LineSegments(
          new THREE.EdgesGeometry(slabGeometry ?? geometry),
          new THREE.LineBasicMaterial(),
        );
        next.add(slab, volume, edges);
        built.push({ key: spec.key, slab, volume, edges });
      }
      group = next;
      floors = built;
      scene.add(next);
      // Вписывание: описанная сфера габарита не зависит от поворота камеры.
      const { width, depth, height } = plan.size;
      radius = Math.max(0.5, Math.sqrt(width * width + depth * depth + height * height) / 2);
      placeCamera();
      fitFrustum();
      applyStyle();
    },
    setHighlight: (current, hover) => {
      currentKey = current;
      hoverKey = hover;
      applyStyle();
    },
    dispose: () => {
      disposed = true;
      if (frame !== 0) cancelAnimationFrame(frame);
      observer.disconnect();
      dom.removeEventListener('pointerdown', onDown);
      dom.removeEventListener('pointermove', onMove);
      dom.removeEventListener('pointerup', onUp);
      dom.removeEventListener('pointercancel', onCancel);
      dom.removeEventListener('pointerleave', onLeave);
      disposeGroup();
      renderer.dispose();
      renderer.forceContextLoss();
      dom.remove();
    },
  };
};
