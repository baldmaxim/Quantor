import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { classifyFiles, FileDropzone } from './FileDropzone';

/**
 * Приём файлов.
 *
 * Проверяется главное обещание экрана: у каждого типа написано, что с ним произойдёт,
 * и неподдерживаемый файл виден как отвергнутый, а не исчезает молча.
 */

const file = (name: string, size = 1024) => {
  const blob = new File([new Uint8Array(size)], name);
  Object.defineProperty(blob, 'size', { value: size });
  return blob;
};

const renderZone = (names: readonly string[], onRemove = vi.fn()) => {
  const picked = classifyFiles(names.map((name) => file(name)));
  render(<FileDropzone files={picked} onAdd={vi.fn()} onRemove={onRemove} />);
  return { onRemove };
};

describe('приём файлов', () => {
  it('объясняет, какие типы принимаются', () => {
    renderZone([]);

    expect(screen.getByText(/ZIP-пакет распознавалки, PDF/)).toBeInTheDocument();
  });

  it('пакет распознавалки помечен как импортируемый', () => {
    renderZone(['01-03-00-01-12_ПД-00260560-АР.zip']);

    expect(screen.getByText('Импортировать')).toBeInTheDocument();
  });

  it('PDF честно подписан: распознавания сейчас не будет', () => {
    renderZone(['чертёж.pdf']);

    expect(screen.getByText(/распознавание — на следующем этапе/)).toBeInTheDocument();
  });

  it('BIM-модель подписана отсутствием обработчика', () => {
    renderZone(['корпус3.nwd']);

    expect(screen.getByText(/обработчик не подключён/)).toBeInTheDocument();
  });

  it('неподдерживаемый файл виден, а не исчезает молча', () => {
    renderZone(['вирус.exe']);

    expect(screen.getByText('Тип не поддерживается')).toBeInTheDocument();
    expect(screen.getByText('вирус.exe')).toBeInTheDocument();
  });

  it('размер файла показан по-русски', () => {
    renderZone(['пакет.zip']);

    const row = screen.getByText('пакет.zip').closest('li');
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText('1 КБ')).toBeInTheDocument();
  });

  it('файл можно убрать из списка', async () => {
    const user = userEvent.setup();
    const { onRemove } = renderZone(['чертёж.pdf']);

    await user.click(screen.getByLabelText('Убрать чертёж.pdf'));

    expect(onRemove).toHaveBeenCalledWith(0);
  });

  it('поле выбора принимает только известные расширения', () => {
    renderZone([]);

    expect(screen.getByLabelText('Выбрать файлы')).toHaveAttribute(
      'accept',
      '.zip,.pdf,.rvt,.nwd,.nwc,.ifc',
    );
  });
});

describe('разбор выбранных файлов', () => {
  it('помечает принимаемые и отвергнутые, не отбрасывая вторые', () => {
    const picked = classifyFiles([file('пакет.zip'), file('вирус.exe')]);

    expect(picked).toHaveLength(2);
    expect(picked[0]?.accepted).toBe(true);
    expect(picked[1]?.accepted).toBe(false);
  });
});
