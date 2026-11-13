import type * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { floor3dFixture } from './floor3d-fixtures';
import { buildFloor3dPlan } from './floor3d-geometry';
import { layerGroupKeys } from './layer-categories';
import { buildFloor3dScene, readFloor3dColors, type IFloor3dPickData } from './floor3d-scene';

const base = floor3dFixture();
const wall = base.walls[0]!;
const plan = buildFloor3dPlan(
  floor3dFixture({
    walls: [
      { ...wall, construction_key: 'a200' },
      { ...wall, construction_key: 'b200' },
      { ...wall, construction_key: 'c80' },
    ],
  }),
);
const keys = layerGroupKeys([
  { id: 'a200', kind: 'masonry', source_layers: ['01_КЛАДКА_200'] },
  { id: 'b200', kind: 'masonry', source_layers: ['01_КЛАДКА_200'] },
  { id: 'c80', kind: 'masonry', source_layers: ['01_КЛАДКА_80'] },
]);

const masonryMeshes = (scene: ReturnType<typeof buildFloor3dScene>): THREE.Mesh[] =>
  scene.pickables.filter((mesh) => (mesh.userData.pick as IFloor3dPickData).category === 'masonry');
const idsOf = (mesh: THREE.Mesh): readonly string[] => (mesh.userData.pick as IFloor3dPickData).ids;

describe('сцена 3D: скрытие конструкций по слоям', () => {
  it('меши кладки делятся по набору слоёв; без ключей - один меш', () => {
    const split = buildFloor3dScene(plan, readFloor3dColors(), { showSlabCap: false, groupKeyOf: keys.keyOf });
    expect(masonryMeshes(split).map(idsOf)).toEqual([['a200', 'b200'], ['c80']]);
    const plain = buildFloor3dScene(plan, readFloor3dColors(), { showSlabCap: false });
    expect(masonryMeshes(plain).map(idsOf)).toEqual([['a200', 'b200', 'c80']]);
    split.dispose();
    plain.dispose();
  });

  it('подгруппа скрывается и показывается без пересборки', () => {
    const scene = buildFloor3dScene(plan, readFloor3dColors(), { showSlabCap: false, groupKeyOf: keys.keyOf });
    const [m200, m80] = masonryMeshes(scene) as [THREE.Mesh, THREE.Mesh];
    const children = scene.group.children.length;
    scene.setHiddenIds(new Set(['a200', 'b200']));
    expect(m200.visible).toBe(false);
    expect(m80.visible).toBe(true);
    expect(scene.group.children).toHaveLength(children);
    scene.setHiddenIds(new Set());
    expect(m200.visible).toBe(true);
    scene.dispose();
  });

  it('скрыта лишь часть id подгруппы - подгруппа видна; категория скрывает всё независимо', () => {
    const scene = buildFloor3dScene(plan, readFloor3dColors(), { showSlabCap: false, groupKeyOf: keys.keyOf });
    const [m200, m80] = masonryMeshes(scene) as [THREE.Mesh, THREE.Mesh];
    scene.setHiddenIds(new Set(['a200']));
    expect(m200.visible).toBe(true);
    scene.setCategoryVisible('masonry', false);
    expect(m200.visible).toBe(false);
    expect(m80.visible).toBe(false);
    // Показ категории не раскрывает подгруппу, скрытую по id.
    scene.setHiddenIds(new Set(['c80']));
    scene.setCategoryVisible('masonry', true);
    expect(m200.visible).toBe(true);
    expect(m80.visible).toBe(false);
    scene.dispose();
  });
});

describe('сцена 3D: перемычка скрывается вместе со стеной-хозяином', () => {
  const lintel = base.lintels[0]!;
  const lintelPlan = buildFloor3dPlan(
    floor3dFixture({
      walls: [
        { ...wall, construction_key: 'm1', kind: 'monolith_wall', family: 'monolith' },
        { ...wall, construction_key: 'k1' },
        { ...wall, construction_key: 'k2' },
      ],
      lintels: [
        { ...lintel, opening_id: 'lm', host_id: 'm1', material: 'monolith' },
        { ...lintel, opening_id: 'lk1', host_id: 'k1', material: 'masonry' },
        { ...lintel, opening_id: 'lk2', host_id: 'k2', material: 'masonry' },
        { ...lintel, opening_id: 'lx', host_id: null, material: 'monolith' },
      ],
      doors: [],
    }),
  );
  const hostKeys = layerGroupKeys([
    { id: 'm1', kind: 'monolith_wall', source_layers: ['02_МОНОЛИТ'] },
    { id: 'k1', kind: 'masonry', source_layers: ['01_КЛАДКА_200'] },
    { id: 'k2', kind: 'masonry', source_layers: ['01_КЛАДКА_80'] },
  ]);
  const build = () =>
    buildFloor3dScene(lintelPlan, readFloor3dColors(), {
      showSlabCap: false,
      groupKeyOf: hostKeys.keyOf,
      hostCategoryOf: hostKeys.categoryOf,
    });
  const lintelMesh = (scene: ReturnType<typeof buildFloor3dScene>, id: string): THREE.Mesh =>
    scene.pickables.find(
      (mesh) =>
        (mesh.userData.pick as IFloor3dPickData).category === 'lintel' &&
        idsOf(mesh).includes(id),
    )!;

  it('строка монолита скрывает перемычку монолитной стены и перемычку без хозяина с монолитом', () => {
    const scene = build();
    const [monolith, withoutHost, masonry] = [
      lintelMesh(scene, 'lm'),
      lintelMesh(scene, 'lx'),
      lintelMesh(scene, 'lk1'),
    ];
    scene.setCategoryVisible('monolith_vertical', false);
    expect(monolith.visible).toBe(false);
    expect(withoutHost.visible).toBe(false);
    expect(masonry.visible).toBe(true);
    scene.dispose();
  });

  it('скрытие стены по слоям (id хозяина) скрывает только её перемычки', () => {
    const scene = build();
    scene.setHiddenIds(new Set(['k1']));
    expect(lintelMesh(scene, 'lk1').visible).toBe(false);
    expect(lintelMesh(scene, 'lk2').visible).toBe(true);
    expect(lintelMesh(scene, 'lm').visible).toBe(true);
    scene.setHiddenIds(new Set());
    expect(lintelMesh(scene, 'lk1').visible).toBe(true);
    scene.dispose();
  });

  it('скрытая «Кладка» не прячет перемычку монолитной стены', () => {
    const scene = build();
    scene.setCategoryVisible('masonry', false);
    expect(lintelMesh(scene, 'lk1').visible).toBe(false);
    expect(lintelMesh(scene, 'lm').visible).toBe(true);
    scene.dispose();
  });
});
