import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CadRemarkEditor } from './CadRemarkEditor';

const mount = (saving = false) => {
  const onSave = vi.fn();
  render(<CadRemarkEditor number={1} saving={saving} onSave={onSave} onCancel={vi.fn()} />);
  return { onSave, field: screen.getByLabelText('Комментарий') };
};

describe('CadRemarkEditor: клавиша Enter', () => {
  it('Enter сохраняет замечание, как кнопка «Сохранить»', () => {
    const { onSave, field } = mount();
    fireEvent.change(field, { target: { value: '  нет стены ' } });
    const allowed = fireEvent.keyDown(field, { key: 'Enter' });
    expect(allowed).toBe(false);
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith({ type: 'missing_wall', comment: 'нет стены' });
  });

  it('Shift+Enter - перенос строки: замечание не сохраняется', () => {
    const { onSave, field } = mount();
    fireEvent.change(field, { target: { value: 'строка' } });
    const allowed = fireEvent.keyDown(field, { key: 'Enter', shiftKey: true });
    expect(allowed).toBe(true);
    expect(onSave).not.toHaveBeenCalled();
  });

  it('Enter при вводе через IME (isComposing) игнорируется', () => {
    const { onSave, field } = mount();
    fireEvent.change(field, { target: { value: 'ни' } });
    fireEvent.keyDown(field, { key: 'Enter', isComposing: true });
    expect(onSave).not.toHaveBeenCalled();
  });

  it('пока замечание сохраняется, Enter второй запрос не отправляет', () => {
    const { onSave, field } = mount(true);
    fireEvent.keyDown(field, { key: 'Enter' });
    expect(onSave).not.toHaveBeenCalled();
  });

  it('кнопка «Сохранить» по-прежнему работает', () => {
    const { onSave } = mount();
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(onSave).toHaveBeenCalledTimes(1);
  });
});
