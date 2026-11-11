import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { ISO_DIRECTION, TOP_DIRECTION } from './floor3d-engine';
import { toScenePoint } from './floor3d-geometry';

const ORIGIN = { x: 0, y: 0, z: 0 };

const cameraAt = (direction: THREE.Vector3): THREE.PerspectiveCamera => {
  const camera = new THREE.PerspectiveCamera(45, 1.5, 0.1, 1000);
  camera.position.copy(direction).multiplyScalar(20);
  camera.lookAt(0, 0, 0);
  camera.updateMatrixWorld(true);
  camera.updateProjectionMatrix();
  return camera;
};

const ndcOf = (camera: THREE.Camera, xMm: number, yMm: number): THREE.Vector3 => {
  const [x, y, z] = toScenePoint(xMm, yMm, 0, ORIGIN);
  return new THREE.Vector3(x, y, z).project(camera);
};

describe('ориентация камеры по умолчанию', () => {
  it('изометрия: камера с юга, наклон около 50 градусов', () => {
    expect(ISO_DIRECTION.x).toBe(0);
    expect(THREE.MathUtils.radToDeg(Math.asin(ISO_DIRECTION.y))).toBeCloseTo(50.2, 0);
    expect(ISO_DIRECTION.z).toBeGreaterThan(0);
  });

  it('изометрия: +x DXF уходит вправо, +y DXF - вверх экрана', () => {
    const camera = cameraAt(ISO_DIRECTION);
    const origin = ndcOf(camera, 0, 0);
    const east = ndcOf(camera, 5000, 0);
    const north = ndcOf(camera, 0, 5000);
    expect(east.x).toBeGreaterThan(origin.x);
    expect(east.y).toBeCloseTo(origin.y, 6);
    expect(north.y).toBeGreaterThan(origin.y);
    expect(north.x).toBeCloseTo(origin.x, 6);
  });

  it('вид сверху: та же ориентация (восток вправо, север вверх)', () => {
    const camera = cameraAt(TOP_DIRECTION);
    const origin = ndcOf(camera, 0, 0);
    expect(ndcOf(camera, 5000, 0).x).toBeGreaterThan(origin.x);
    expect(ndcOf(camera, 0, 5000).y).toBeGreaterThan(origin.y);
  });
});
