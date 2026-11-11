import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { floor3dFixture } from './floor3d-fixtures';
import { buildFloor3dPlan, highlightOf } from './floor3d-geometry';
import { buildFloor3dScene, pickOf, readFloor3dColors, type IFloor3dPickData } from './floor3d-scene';

describe('сцена 3D-вида (без WebGL)', () => {
  const plan = buildFloor3dPlan(floor3dFixture());
  const scene = buildFloor3dScene(plan, readFloor3dColors(), { showSlabCap: true });

  it('меш на категорию, не на конструкцию; в клик входят плита, кладка, перемычки и отверстия', () => {
    const categories = scene.pickables.map((mesh) => (mesh.userData.pick as IFloor3dPickData).category);
    expect(categories).toEqual(['slab', 'masonry', 'lintel', 'hole', 'hole']);
    expect(scene.slabCap).not.toBeNull();
  });

  it('грань находит свой элемент; грань вне карты - null', () => {
    const masonry = scene.pickables.find((mesh) => (mesh.userData.pick as IFloor3dPickData).category === 'masonry');
    expect(masonry).toBeDefined();
    expect(pickOf(masonry!, 0)).toEqual({ kind: 'prism', category: 'masonry', id: 'w1' });
    expect(pickOf(masonry!, 100000)).toBeNull();
    expect(pickOf(masonry!, undefined)).toBeNull();
  });

  it('отверстия: кандидат - своя заливка, включённое и «Не отверстие» - невидимый меш для клика', () => {
    const holes = scene.pickables.filter((mesh) => (mesh.userData.pick as IFloor3dPickData).kind === 'hole');
    expect(holes.map((mesh) => pickOf(mesh, 0)?.id)).toEqual(['h1', 'h2']);
    const hidden = holes[1]!;
    expect((hidden.material as THREE.Material).visible).toBe(false);
    expect((hidden.userData.pick as IFloor3dPickData).ids).toEqual(['h2', 'h3']);
    expect(pickOf(hidden, 2)?.id).toBe('h3');
  });

  it('«Не отверстие» рисуется контуром токена --muted, плита по нему не вырезана', () => {
    const colors = { ...readFloor3dColors(), muted: 'rgb(1, 2, 3)' };
    const own = buildFloor3dScene(plan, colors, { showSlabCap: false });
    const loops = own.group.children.filter((child): child is THREE.LineLoop => child instanceof THREE.LineLoop);
    expect(loops).toHaveLength(3);
    const muted = new THREE.Color(colors.muted).getHex();
    expect(loops.filter((loop) => (loop.material as THREE.LineBasicMaterial).color.getHex() === muted)).toHaveLength(1);
    own.dispose();
  });

  it('выделение: оверлей поверх меша, в клик не входит, заменяется и снимается', () => {
    const own = buildFloor3dScene(plan, readFloor3dColors(), { showSlabCap: false });
    const before = own.group.children.length;
    own.setHighlight(highlightOf(plan, { kind: 'prism', category: 'masonry', id: 'w1' }));
    expect(own.group.children).toHaveLength(before + 1);
    const overlay = own.group.children[before] as THREE.Group;
    expect(overlay.children.some((child) => child instanceof THREE.LineSegments)).toBe(true);
    own.setHighlight(highlightOf(plan, { kind: 'hole', category: 'hole', id: 'h2' }));
    expect(own.group.children).toHaveLength(before + 1);
    expect((own.group.children[before] as THREE.Group).children.some((child) => child instanceof THREE.LineLoop)).toBe(true);
    expect(own.pickables).toHaveLength(scene.pickables.length);
    own.setHighlight(null);
    expect(own.group.children).toHaveLength(before);
    own.dispose();
  });

  it('без галки плиты сверху копии нет; dispose не падает', () => {
    const plain = buildFloor3dScene(plan, readFloor3dColors(), { showSlabCap: false });
    expect(plain.slabCap).toBeNull();
    plain.dispose();
    scene.dispose();
  });
});
