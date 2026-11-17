import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import type { IModelElement } from './model-elements';
import { partSignature, partToSpeckle, planContentUpdate, speckleIdOf } from './model-speckle';

const triangle = (indexed: boolean): THREE.BufferGeometry => {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    'position',
    new THREE.Float32BufferAttribute([1, 2, 3, 4, 2, 3, 1, 5, 3], 3),
  );
  if (indexed) geometry.setIndex([0, 1, 2]);
  return geometry;
};

const node = (name: string, geometry: THREE.BufferGeometry): THREE.Object3D => {
  const holder = new THREE.Object3D();
  holder.name = name;
  holder.add(new THREE.Mesh(geometry));
  return holder;
};

const wall: IModelElement = {
  id: '2Fk$wall',
  category: 'wall',
  ifc_class: 'IfcWall',
  name: 'Стена 200',
  type: 'Базовая стена',
  discipline: 'ARCH',
  props: { 'Pset.Fire': 'EI60' },
};

describe('часть пакета -> объекты Speckle', () => {
  it('сетка переводится в оси Speckle (Z вверх) поворотом, грани сохраняют порядок', () => {
    const scene = new THREE.Group();
    scene.add(node('2Fk$wall', triangle(true)));
    const result = partToSpeckle('k1', 'ARCH', scene, new Map([[wall.id, wall]]));
    const mesh = result.objects.find((item) => item.speckle_type === 'Objects.Geometry.Mesh');
    expect(mesh?.units).toBe('m');
    // (x, y, z) glTF -> (x, -z, y): точка (1, 2, 3) становится (1, -3, 2)
    expect(mesh?.vertices).toEqual([1, -3, 2, 4, -3, 2, 1, -3, 5]);
    expect(mesh?.faces).toEqual([3, 0, 1, 2]);
  });

  it('геометрия без индексов даёт треугольники подряд', () => {
    const scene = new THREE.Group();
    scene.add(node('a', triangle(false)));
    const mesh = partToSpeckle('k', 'PL', scene, null).objects.find(
      (item) => item.speckle_type === 'Objects.Geometry.Mesh',
    );
    expect(mesh?.faces).toEqual([3, 0, 1, 2]);
  });

  it('элемент несёт GlobalId, категорию, класс и свойства, ссылка на сетку по id', () => {
    const scene = new THREE.Group();
    scene.add(node('2Fk$wall', triangle(true)));
    const result = partToSpeckle('k1', 'ARCH', scene, new Map([[wall.id, wall]]));
    const id = speckleIdOf('k1', '2Fk$wall');
    const element = result.objects.find((item) => item.id === id);
    expect(element).toMatchObject({
      applicationId: '2Fk$wall',
      category: 'wall',
      ifcClass: 'IfcWall',
      discipline: 'ARCH',
      name: 'Стена 200',
      properties: { 'Параметры IFC': { 'Pset.Fire': 'EI60' } },
    });
    expect(element?.displayValue).toEqual([
      { speckle_type: 'reference', referencedId: `${id}:mesh` },
    ]);
    expect(result.speckleIds.get('2Fk$wall')).toBe(id);
  });

  it('корень ссылается на все элементы, закрытие содержит элемент и сетку', () => {
    const scene = new THREE.Group();
    scene.add(node('a', triangle(true)), node('b', triangle(true)));
    const [root, ...rest] = partToSpeckle('k', 'ARCH', scene, null).objects;
    expect(root?.speckle_type).toBe('Base');
    expect(root?.elements).toEqual([
      { speckle_type: 'reference', referencedId: 'k:a' },
      { speckle_type: 'reference', referencedId: 'k:b' },
    ]);
    expect(Object.keys(root?.__closure ?? {}).sort()).toEqual(
      ['k:a', 'k:a:mesh', 'k:b', 'k:b:mesh'].sort(),
    );
    expect(rest).toHaveLength(4);
  });

  it('элемент без геометрии пропускается, без свойств берётся дисциплина части', () => {
    const scene = new THREE.Group();
    const empty = new THREE.Object3D();
    empty.name = 'empty';
    scene.add(empty, node('c', triangle(true)));
    const result = partToSpeckle('k', 'VAC', scene, null);
    expect(result.speckleIds.has('empty')).toBe(false);
    const element = result.objects.find((item) => item.id === 'k:c');
    expect(element).toMatchObject({ discipline: 'VAC', category: null, name: 'c' });
  });

  it('безымянная обёртка сцены не мешает найти элементы', () => {
    const scene = new THREE.Group();
    const wrapper = new THREE.Group();
    wrapper.add(node('inner', triangle(true)));
    scene.add(wrapper);
    expect(partToSpeckle('k', 'ARCH', scene, null).speckleIds.has('inner')).toBe(true);
  });

  it('категория берётся из имени материала GLB, если свойств нет', () => {
    const scene = new THREE.Group();
    const wallNode = node('w1', triangle(true));
    ((wallNode.children[0] as THREE.Mesh).material as THREE.Material).name = 'cat:wall';
    scene.add(wallNode);
    const element = partToSpeckle('k', 'ARCH', scene, null).objects.find(
      (item) => item.id === 'k:w1',
    );
    expect(element?.category).toBe('wall');
  });

  it('фильтр категорий пропускает остальные элементы', () => {
    const scene = new THREE.Group();
    const wallNode = node('w1', triangle(true));
    const chairNode = node('c1', triangle(true));
    ((wallNode.children[0] as THREE.Mesh).material as THREE.Material).name = 'cat:wall';
    ((chairNode.children[0] as THREE.Mesh).material as THREE.Material).name = 'cat:furniture';
    scene.add(wallNode, chairNode);
    const result = partToSpeckle('k', 'ARCH', scene, null, { categories: new Set(['wall']) });
    expect([...result.speckleIds.keys()]).toEqual(['w1']);
  });

  it('этаж части записывается в элемент: по щелчку видно, из какого он этажа', () => {
    const scene = new THREE.Group();
    scene.add(node('a', triangle(true)));
    const element = partToSpeckle('k', 'ARCH', scene, null, { group: 'storey-7' }).objects.find(
      (item) => item.id === 'k:a',
    );
    expect(element?.storeyKey).toBe('storey-7');
  });

  it('одинаковый GlobalId в разных частях получает разные id объектов', () => {
    expect(speckleIdOf('part1', 'gid')).not.toBe(speckleIdOf('part2', 'gid'));
  });
});

describe('обновление содержимого просмотрщика', () => {
  const sig = (...entries: Array<[string, string]>): Map<string, string> => new Map(entries);

  it('неизменившиеся части остаются, новые добавляются, ушедшие выгружаются', () => {
    const plan = planContentUpdate(
      sig(['a', 'ARCH|s1|0'], ['b', 'ARCH|s2|1'], ['c', 'PL|s1|0']),
      sig(['a', 'ARCH|s1|0'], ['b2', 'ARCH|s2|1'], ['c', 'PL|s1|0']),
      false,
    );
    expect(plan).toEqual({ remove: ['b'], add: ['b2'], kept: 2 });
  });

  it('та же часть с другой подписью (другой этаж) грузится заново', () => {
    const plan = planContentUpdate(sig(['a', 'ARCH|s1|0']), sig(['a', 'ARCH|s2|1']), false);
    expect(plan).toEqual({ remove: ['a'], add: ['a'], kept: 0 });
  });

  it('полная замена выгружает и грузит всё, что нужно', () => {
    const plan = planContentUpdate(sig(['a', 'x'], ['b', 'y']), sig(['a', 'x'], ['b', 'y']), true);
    expect(plan).toEqual({ remove: ['a', 'b'], add: ['a', 'b'], kept: 0 });
  });

  it('пустой просмотрщик заполняется всеми частями в порядке запроса', () => {
    const plan = planContentUpdate(sig(), sig(['b', 'x'], ['a', 'y']), false);
    expect(plan).toEqual({ remove: [], add: ['b', 'a'], kept: 0 });
  });

  it('подпись части: дисциплина, этаж и уровень', () => {
    const buffer = new ArrayBuffer(1);
    expect(partSignature({ key: 'k', discipline: 'KR', buffer, group: 's3', level: 2 })).toBe(
      'KR|s3|2',
    );
    expect(partSignature({ key: 'k', discipline: 'KR', buffer })).toBe('KR||0');
  });
});
