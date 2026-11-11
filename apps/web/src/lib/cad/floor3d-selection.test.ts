import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { floor3dFixture } from './floor3d-fixtures';
import { buildFloor3dPlan, highlightOf, highlightsOf, visibilityOf } from './floor3d-geometry';
import { buildFloor3dScene, pickOf, readFloor3dColors, type IFloor3dPickData } from './floor3d-scene';

const withWalls = () => {
  const base = floor3dFixture();
  const wall = base.walls[0]!;
  return floor3dFixture({
    walls: [
      wall,
      { ...wall, construction_key: 'w3', kind: 'frame_partition', family: 'frame_partition' },
      { ...wall, construction_key: 'w4', kind: 'monolith_wall', family: 'monolith' },
    ],
  });
};

describe('подсветка нескольких конструкций', () => {
  const plan = buildFloor3dPlan(withWalls());

  it('все призмы стен, перегородок и плиты из общего выбора; чужие id и перемычки/двери по своему id - нет', () => {
    const ids = highlightsOf(plan, new Set(['w1', 'w3', 'w4', 'slab', 'o1', 'nope'])).map((item) =>
      item.kind === 'prism' ? item.spec.id : '',
    );
    expect(ids.sort()).toEqual(['slab', 'w1', 'w3', 'w4']);
    expect(highlightsOf(plan, new Set())).toEqual([]);
  });

  it('выбранная стена подсвечивает свои перемычки и двери по host_id, чужие - нет', () => {
    const base = withWalls();
    const lintel = base.lintels[0]!;
    const door = base.doors![0]!;
    const hosted = buildFloor3dPlan({
      ...base,
      lintels: [
        { ...lintel, opening_id: 'l1', host_id: 'w1' },
        { ...lintel, opening_id: 'l2', host_id: 'w3' },
        { ...lintel, opening_id: 'l3', host_id: null },
        { ...lintel, opening_id: 'l4' },
      ],
      doors: [
        { ...door, opening_id: 'd1', host_id: 'w1' },
        { ...door, opening_id: 'd2', host_id: 'w3' },
      ],
    });
    const ids = (selected: string[]) =>
      highlightsOf(hosted, new Set(selected))
        .map((item) => (item.kind === 'prism' ? `${item.spec.category}:${item.spec.id}` : ''))
        .sort();
    expect(ids(['w1'])).toEqual(['door:d1', 'lintel:l1', 'masonry:w1']);
    expect(ids(['w3'])).toEqual(['door:d2', 'frame_partition:w3', 'lintel:l2']);
    expect(ids(['l1', 'd1'])).toEqual([]);
  });

  it('каркасная перегородка (family frame_partition) - своя категория призмы и видимости', () => {
    const frame = plan.prisms.find((item) => item.id === 'w3')!;
    expect(frame.category).toBe('frame_partition');
    expect(visibilityOf(frame)).toBe('frame_partition');
    expect(visibilityOf(plan.prisms.find((item) => item.id === 'w1')!)).toBe('masonry');
  });

  it('оверлей группы - один слитый объект, снимается', () => {
    const scene = buildFloor3dScene(plan, readFloor3dColors(), { showSlabCap: false });
    const before = scene.group.children.length;
    scene.setHighlight(highlightsOf(plan, new Set(['w1', 'w3', 'w4', 'slab'])));
    expect(scene.group.children).toHaveLength(before + 1);
    const overlay = scene.group.children[before] as THREE.Group;
    expect(overlay.children.filter((child) => child instanceof THREE.Mesh)).toHaveLength(1);
    scene.setHighlight([highlightOf(plan, { kind: 'hole', category: 'hole', id: 'h2' })!, ...highlightsOf(plan, new Set(['w1']))]);
    expect(scene.group.children).toHaveLength(before + 1);
    scene.setHighlight([]);
    expect(scene.group.children).toHaveLength(before);
    scene.dispose();
  });
});

describe('видимость категорий в сцене', () => {
  const plan = buildFloor3dPlan(withWalls());
  const categoryMeshes = (scene: ReturnType<typeof buildFloor3dScene>, category: string) =>
    scene.pickables.filter((mesh) => (mesh.userData.pick as IFloor3dPickData).category === category);

  it('меш каркасных перегородок отдельный, клик отдаёт категорию frame_partition и id перегородки', () => {
    const scene = buildFloor3dScene(plan, readFloor3dColors(), { showSlabCap: false });
    const masonry = categoryMeshes(scene, 'masonry');
    expect(masonry.map((mesh) => (mesh.userData.pick as IFloor3dPickData).ids)).toEqual([['w1']]);
    const frame = categoryMeshes(scene, 'frame_partition');
    expect(frame.map((mesh) => (mesh.userData.pick as IFloor3dPickData).ids)).toEqual([['w3']]);
    expect(pickOf(frame[0]!, 0)).toEqual({ kind: 'prism', category: 'frame_partition', id: 'w3' });
    scene.dispose();
  });

  it('setCategoryVisible скрывает меши, рёбра, отверстия и копию плиты без пересборки', () => {
    const scene = buildFloor3dScene(plan, readFloor3dColors(), { showSlabCap: true });
    const meshesBefore = [...scene.pickables];
    scene.setCategoryVisible('slab', false);
    expect(categoryMeshes(scene, 'slab').every((mesh) => !mesh.visible)).toBe(true);
    expect(categoryMeshes(scene, 'hole').every((mesh) => !mesh.visible)).toBe(true);
    expect(scene.slabCap?.visible).toBe(false);
    expect(categoryMeshes(scene, 'monolith').every((mesh) => mesh.visible)).toBe(true);
    expect(scene.pickables).toEqual(meshesBefore);

    scene.setCategoryVisible('frame_partition', false);
    expect(categoryMeshes(scene, 'masonry').every((mesh) => mesh.visible)).toBe(true);
    expect(categoryMeshes(scene, 'frame_partition').every((mesh) => !mesh.visible)).toBe(true);

    scene.setCategoryVisible('slab', true);
    expect(categoryMeshes(scene, 'slab')[0]!.visible).toBe(true);
    scene.setCategoryVisible('lintel', false);
    expect(categoryMeshes(scene, 'lintel').every((mesh) => !mesh.visible)).toBe(true);
    scene.setCategoryVisible('door', false);
    expect(categoryMeshes(scene, 'door').every((mesh) => !mesh.visible)).toBe(true);
    scene.dispose();
  });
});
