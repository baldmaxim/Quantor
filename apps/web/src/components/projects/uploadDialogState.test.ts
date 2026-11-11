import { describe, expect, it } from 'vitest';

import { getUploadDialogState } from '@/components/projects/uploadDialogState';

const done = { stage: 'готово' } as const;
const failed = { stage: 'ошибка' } as const;

describe('getUploadDialogState', () => {
  it('пустая очередь в начале — «Загрузить» неактивна', () => {
    expect(getUploadDialogState({ pendingCount: 0, running: false, items: [] })).toEqual({
      primary: 'upload',
      canUpload: false,
    });
  });

  it('есть выбранные файлы — «Загрузить» активна', () => {
    expect(getUploadDialogState({ pendingCount: 2, running: false, items: [] })).toEqual({
      primary: 'upload',
      canUpload: true,
    });
  });

  it('идёт загрузка — неактивна', () => {
    const state = getUploadDialogState({ pendingCount: 1, running: true, items: [done] });
    expect(state.canUpload).toBe(false);
    expect(state.primary).toBe('upload');
  });

  it('всё загружено и очередь пуста — основная «Готово», «Загрузить» неактивна', () => {
    expect(getUploadDialogState({ pendingCount: 0, running: false, items: [done, done] })).toEqual({
      primary: 'done',
      canUpload: false,
    });
  });

  it('часть с ошибкой осталась в очереди — «Загрузить» активна для повтора', () => {
    expect(getUploadDialogState({ pendingCount: 1, running: false, items: [done, failed] })).toEqual({
      primary: 'upload',
      canUpload: true,
    });
  });
});
