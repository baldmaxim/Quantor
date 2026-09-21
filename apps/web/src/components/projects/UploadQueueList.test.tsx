import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { UploadItem } from './UploadQueue';
import { UploadQueueList } from './UploadQueueList';

/**
 * Ход загрузки.
 *
 * Список общий для обоих окон, и проверяется именно то, что разошлось в копиях:
 * все пять состояний названы, а повторная загрузка не выглядит ошибкой.
 */

const item = (patch: Partial<UploadItem>): UploadItem => ({
  id: '0-чертёж.pdf',
  name: 'чертёж.pdf',
  size: 1024,
  stage: 'ожидание',
  fraction: null,
  errorCode: null,
  errorText: null,
  duplicate: false,
  ...patch,
});

describe('ход загрузки', () => {
  it('называет каждое состояние очереди', () => {
    render(
      <UploadQueueList
        items={[
          item({ id: '1', stage: 'ожидание' }),
          item({ id: '2', stage: 'загрузка', fraction: 0.5 }),
          item({ id: '3', stage: 'готово', fraction: 1 }),
          item({ id: '4', stage: 'ошибка', errorCode: 'EMPTY_FILE', errorText: 'Файл пуст.' }),
          item({ id: '5', stage: 'отменено' }),
        ]}
      />,
    );

    for (const stage of ['ожидание', 'загрузка', 'готово', 'ошибка', 'отменено']) {
      expect(screen.getByText(stage), stage).toBeInTheDocument();
    }
  });

  it('показывает долю отправленного, пока файл идёт', () => {
    render(<UploadQueueList items={[item({ stage: 'загрузка', fraction: 0.5 })]} />);

    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '50');
  });

  it('повтор — не ошибка: файл уже был', () => {
    render(<UploadQueueList items={[item({ stage: 'готово', fraction: 1, duplicate: true })]} />);

    expect(screen.getByText('уже был')).toBeInTheDocument();
  });

  it('показывает код ошибки рядом с объяснением', () => {
    render(
      <UploadQueueList
        items={[item({ stage: 'ошибка', errorCode: 'EMPTY_FILE', errorText: 'Файл пуст.' })]}
      />,
    );

    expect(screen.getByText(/Файл пуст\./)).toBeInTheDocument();
    // Код стабилен и пригоден для поиска в логах, в отличие от текста.
    expect(screen.getByText(/EMPTY_FILE/)).toBeInTheDocument();
  });

  it('пустая очередь не рисует пустую рамку', () => {
    const { container } = render(<UploadQueueList items={[]} />);

    expect(container).toBeEmptyDOMElement();
  });
});
