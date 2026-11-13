import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { orbitAroundPivot } from './pivot-orbit';

const polarOf = (cam: THREE.Vector3, target: THREE.Vector3): number => {
  const offset = cam.clone().sub(target);
  return Math.acos(offset.y / offset.length());
};

const CAM = new THREE.Vector3(10, 8, 12);
const TARGET = new THREE.Vector3(1, 2, 3);
const PIVOT = new THREE.Vector3(-4, 1, 6);
const MIN = 0.01;
const MAX = Math.PI - 0.01;

describe('orbitAroundPivot', () => {
  it('сохраняет расстояния камеры и цели до pivot', () => {
    const r = orbitAroundPivot(CAM, TARGET, PIVOT, 0.7, -0.3, MIN, MAX);
    expect(r.cameraPos.distanceTo(PIVOT)).toBeCloseTo(CAM.distanceTo(PIVOT), 9);
    expect(r.target.distanceTo(PIVOT)).toBeCloseTo(TARGET.distanceTo(PIVOT), 9);
  });

  it('сохраняет расстояние камера - цель', () => {
    const r = orbitAroundPivot(CAM, TARGET, PIVOT, -1.1, 0.4, MIN, MAX);
    expect(r.cameraPos.distanceTo(r.target)).toBeCloseTo(CAM.distanceTo(TARGET), 9);
  });

  it('pivot = цель: цель не двигается', () => {
    const r = orbitAroundPivot(CAM, TARGET, TARGET, 0.9, 0.2, MIN, MAX);
    expect(r.target.distanceTo(TARGET)).toBeCloseTo(0, 9);
    expect(r.cameraPos.distanceTo(TARGET)).toBeCloseTo(CAM.distanceTo(TARGET), 9);
  });

  it('азимут вокруг цели не меняет полярный угол, возвышение меняет на заданную величину', () => {
    const before = polarOf(CAM, TARGET);
    const az = orbitAroundPivot(CAM, TARGET, TARGET, 0.5, 0, MIN, MAX);
    expect(polarOf(az.cameraPos, az.target)).toBeCloseTo(before, 9);
    const el = orbitAroundPivot(CAM, TARGET, TARGET, 0, 0.2, MIN, MAX);
    expect(polarOf(el.cameraPos, el.target)).toBeCloseTo(before + 0.2, 9);
  });

  it('кламп полярного угла по maxPolar и minPolar', () => {
    const max = Math.PI / 2 - 0.03;
    const down = orbitAroundPivot(CAM, TARGET, PIVOT, 0, 3, MIN, max);
    expect(polarOf(down.cameraPos, down.target)).toBeCloseTo(max, 9);
    const up = orbitAroundPivot(CAM, TARGET, PIVOT, 0, -3, 0.2, MAX);
    expect(polarOf(up.cameraPos, up.target)).toBeCloseTo(0.2, 9);
  });

  it('не мутирует входные векторы', () => {
    const cam = CAM.clone();
    const tgt = TARGET.clone();
    const piv = PIVOT.clone();
    orbitAroundPivot(cam, tgt, piv, 0.8, 0.3, MIN, MAX);
    expect(cam.equals(CAM)).toBe(true);
    expect(tgt.equals(TARGET)).toBe(true);
    expect(piv.equals(PIVOT)).toBe(true);
  });
});
