import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { classifyFiles, FileDropzone, packagePicked } from './FileDropzone';

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

describe('выбор папки', () => {
  const setFolderSupport = (supported: boolean) => {
    if (supported) {
      Object.defineProperty(HTMLInputElement.prototype, 'webkitdirectory', {
        configurable: true,
        value: false,
        writable: true,
      });
    } else {
      Reflect.deleteProperty(HTMLInputElement.prototype, 'webkitdirectory');
    }
  };

  afterEach(() => setFolderSupport(false));

  it('кнопка «Выбрать папку» скрыта там, где браузер не умеет выбирать папки', () => {
    setFolderSupport(false);
    render(<FileDropzone files={[]} onAdd={vi.fn()} onRemove={vi.fn()} onAddFolder={vi.fn()} />);

    expect(screen.queryByRole('button', { name: 'Выбрать папку' })).toBeNull();
  });

  it('без обработчика папок кнопки нет даже в поддерживающем браузере', () => {
    setFolderSupport(true);
    render(<FileDropzone files={[]} onAdd={vi.fn()} onRemove={vi.fn()} />);

    expect(screen.queryByRole('button', { name: 'Выбрать папку' })).toBeNull();
  });

  it('выбранная папка уходит в onAddFolder с относительными путями', async () => {
    setFolderSupport(true);
    const user = userEvent.setup();
    const onAddFolder = vi.fn();
    render(
      <FileDropzone files={[]} onAdd={vi.fn()} onRemove={vi.fn()} onAddFolder={onAddFolder} />,
    );

    expect(screen.getByRole('button', { name: 'Выбрать папку' })).toBeInTheDocument();
    const input = screen.getByLabelText('Выбрать папку', { selector: 'input' });
    expect(input).toHaveAttribute('webkitdirectory');

    const inner = new File(['x'], 'АР_blocks.json');
    Object.defineProperty(inner, 'webkitRelativePath', { value: 'TENDER/data/АР_blocks.json' });
    await user.upload(input as HTMLInputElement, inner);

    expect(onAddFolder).toHaveBeenCalledWith([{ file: inner, path: 'TENDER/data/АР_blocks.json' }]);
  });

  it('пакет из папки подписан и помечен как импортируемый', () => {
    const pkg = {
      stem: 'АР',
      pdf: file('АР.pdf'),
      resultsMd: file('АР_results.md'),
      resultsHtml: file('АР_results.html'),
      blocks: file('АР_blocks.json'),
    };
    render(<FileDropzone files={[packagePicked(pkg)]} onAdd={vi.fn()} onRemove={vi.fn()} />);

    expect(screen.getByText('АР.zip')).toBeInTheDocument();
    expect(screen.getByText('пакет из папки: 4 файла')).toBeInTheDocument();
    expect(screen.getByText('Импортировать')).toBeInTheDocument();
  });
});
