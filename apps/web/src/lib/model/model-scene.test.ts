import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { defaultHouseDisciplines, elementIdOf } from './model-scene';

describe('выбор элемента в 3D', () => {
  const build = () => {
    const root = new THREE.Group();
    root.userData.modelRoot = true;
    const part = new THREE.Group();
    const node = new THREE.Object3D();
    node.name = '2Fk$wall';
    const mesh = new THREE.Mesh();
    node.add(mesh);
    part.add(node);
    root.add(part);
    return { root, part, node, mesh };
  };

  it('имя узла элемента находится вверх по родителям от меша', () => {
    const { mesh, node } = build();
    expect(elementIdOf(mesh)).toBe('2Fk$wall');
    expect(elementIdOf(node)).toBe('2Fk$wall');
  });

  it('собственное имя меша важнее имени родителя', () => {
    const { mesh } = build();
    mesh.name = 'door-7';
    expect(elementIdOf(mesh)).toBe('door-7');
  });

  it('безымянная цепочка до корня модели - не элемент', () => {
    const { part, root } = build();
    const stray = new THREE.Mesh();
    part.add(stray);
    expect(elementIdOf(stray)).toBeNull();
    expect(elementIdOf(root)).toBeNull();
    expect(elementIdOf(null)).toBeNull();
  });
});

describe('дисциплины «Всего дома» по умолчанию', () => {
  it('АР, если есть, иначе первая по алфавиту, пустая модель - ничего', () => {
    expect([...defaultHouseDisciplines(['ARCH', 'PL', 'VAC'])]).toEqual(['ARCH']);
    expect([...defaultHouseDisciplines(['FF', 'PL'])]).toEqual(['FF']);
    expect(defaultHouseDisciplines([]).size).toBe(0);
  });
});
