import { describe, expect, it } from 'vitest';

import { DEFAULT_NEXT, safeNextPath } from './safe-next';

describe('возврат после входа', () => {
  it('путь внутри портала сохраняется', () => {
    expect(safeNextPath('/projects/42/workspace?revision=1')).toBe(
      '/projects/42/workspace?revision=1',
    );
  });

  it.each(['https://evil.example', '//evil.example', '/\\evil.example', 'projects', '', null])(
    '%s не уводит за пределы портала',
    (raw) => {
      expect(safeNextPath(raw)).toBe(DEFAULT_NEXT);
    },
  );

  it('из повторённого параметра берётся первый', () => {
    expect(safeNextPath(['/calc', '//evil.example'])).toBe('/calc');
  });
});
