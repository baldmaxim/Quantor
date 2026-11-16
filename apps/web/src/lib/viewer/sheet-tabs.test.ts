import { describe, expect, it } from 'vitest';

import {
  addSheetTab,
  closeSheetTab,
  openSheetTabs,
  opensInNewTab,
  parseSheetTabs,
  replaceSheetTab,
  serializeSheetTabs,
} from './sheet-tabs';

describe('вкладки листов', () => {
  it('разбор адреса отбрасывает мусор, повторы и листы вне ревизии', () => {
    expect(parseSheetTabs('3, 1,x,3,0,9,2.5,2', 5)).toEqual([3, 1, 2]);
    expect(parseSheetTabs(null, 5)).toEqual([]);
    expect(parseSheetTabs('1,2', 0)).toEqual([]);
  });

  it('активный лист вне адреса дописывается в конец', () => {
    expect(openSheetTabs([1, 3], 5)).toEqual([1, 3, 5]);
    expect(openSheetTabs([1, 3], 3)).toEqual([1, 3]);
    expect(openSheetTabs([], 2)).toEqual([2]);
    expect(openSheetTabs([1], null)).toEqual([1]);
  });

  it('обычный переход заменяет активную вкладку, открытый лист только активирует', () => {
    expect(replaceSheetTab([1, 3, 5], 3, 4)).toEqual([1, 4, 5]);
    expect(replaceSheetTab([1, 3, 5], 3, 5)).toEqual([1, 3, 5]);
    expect(replaceSheetTab([], 2, 4)).toEqual([4]);
  });

  it('новая вкладка встаёт справа от активной и не дублируется', () => {
    expect(addSheetTab([1, 3, 5], 3, 4)).toEqual([1, 3, 4, 5]);
    expect(addSheetTab([1, 3], 3, 1)).toEqual([1, 3]);
    expect(addSheetTab([], 2, 7)).toEqual([2, 7]);
  });

  it('закрытие активной отдаёт фокус соседу справа, у крайней - слева', () => {
    expect(closeSheetTab([1, 3, 5], 3, 3)).toEqual({ tabs: [1, 5], active: 5 });
    expect(closeSheetTab([1, 3, 5], 5, 5)).toEqual({ tabs: [1, 3], active: 3 });
    expect(closeSheetTab([1, 3, 5], 1, 5)).toEqual({ tabs: [1, 3], active: 1 });
  });

  it('последнюю вкладку и незнакомый лист закрыть нельзя', () => {
    expect(closeSheetTab([2], 2, 2)).toEqual({ tabs: [2], active: 2 });
    expect(closeSheetTab([1, 2], 1, 9)).toEqual({ tabs: [1, 2], active: 1 });
  });

  it('одна вкладка параметра адреса не требует', () => {
    expect(serializeSheetTabs([4])).toBeNull();
    expect(serializeSheetTabs([])).toBeNull();
    expect(serializeSheetTabs([1, 4])).toBe('1,4');
  });

  it('новая вкладка - Ctrl или Cmd со щелчком либо средняя кнопка', () => {
    expect(opensInNewTab({ button: 0, ctrlKey: true, metaKey: false })).toBe(true);
    expect(opensInNewTab({ button: 0, ctrlKey: false, metaKey: true })).toBe(true);
    expect(opensInNewTab({ button: 1, ctrlKey: false, metaKey: false })).toBe(true);
    expect(opensInNewTab({ button: 0, ctrlKey: false, metaKey: false })).toBe(false);
    expect(opensInNewTab({ button: 2, ctrlKey: true, metaKey: false })).toBe(false);
  });
});
