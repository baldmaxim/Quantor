import type { DocumentRead } from '@quantor/api-client';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';

import { collapsedKey, DocumentSections } from './DocumentSections';

const doc = (
  id: string,
  name: string,
  kind: DocumentRead['document_kind'] = 'pdf',
): DocumentRead => ({
  id,
  project_id: 'p-1',
  display_name: name,
  discipline: null,
  document_kind: kind,
  created_at: '2026-09-01T10:00:00Z',
  updated_at: '2026-09-01T10:00:00Z',
});

const DOCS = [
  doc('1', 'М-П-АР1.1_ver5.pdf'),
  doc('2', 'М-П-АР1.1_ver5.zip', 'recognized_package'),
  doc('3', 'М-П-ИОС2.1_ver4.pdf'),
  doc('4', 'М-П-ИОС2.2_ver4.pdf'),
  doc('5', 'Письмо.pdf'),
  doc('6', 'Одинокий.zip', 'recognized_package'),
];

const renderSections = () =>
  render(<DocumentSections projectId="p-1" documents={DOCS} revisionsOf={() => null} />);

describe('документы по разделам', () => {
  beforeEach(() => window.localStorage.clear());

  it('заголовки групп с числом документов, пакет привязан к PDF', () => {
    renderSections();

    const ar = screen.getByRole('button', { name: /Архитектурные решения/ });
    expect(ar).toHaveTextContent('1');
    expect(ar).toHaveAttribute('aria-expanded', 'true');
    expect(
      screen.getByRole('button', { name: /Водоснабжение и пожаротушение \(ИОС2\)/ }),
    ).toHaveTextContent('2');
    expect(screen.getByRole('button', { name: /Прочее/ })).toHaveTextContent('1');
    expect(screen.getByRole('button', { name: /Пакеты распознавания/ })).toHaveTextContent('1');

    // ZIP с PDF не имеет своей строки, а у PDF есть пометка.
    expect(screen.queryByText('М-П-АР1.1_ver5.zip')).not.toBeInTheDocument();
    expect(screen.getByText(/пакет распознавания/)).toBeInTheDocument();
    expect(screen.getByText('Одинокий.zip')).toBeInTheDocument();
  });

  it('группа сворачивается и состояние запоминается по проекту', async () => {
    const user = userEvent.setup();
    renderSections();

    const button = screen.getByRole('button', { name: /Водоснабжение/ });
    await user.click(button);

    expect(button).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('М-П-ИОС2.1_ver4.pdf')).not.toBeInTheDocument();
    expect(window.localStorage.getItem(collapsedKey('p-1'))).toBe('["ios2"]');
  });

  it('свёрнутое состояние восстанавливается', () => {
    window.localStorage.setItem(collapsedKey('p-1'), '["ios2"]');
    renderSections();

    expect(screen.getByRole('button', { name: /Водоснабжение/ })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    const ar = screen.getByRole('region', { name: 'Архитектурные решения' });
    expect(within(ar).getByText('М-П-АР1.1_ver5.pdf')).toBeInTheDocument();
  });

  it('повреждённое хранилище не ломает список', () => {
    window.localStorage.setItem(collapsedKey('p-1'), '{не json');
    renderSections();

    expect(screen.getByRole('button', { name: /Архитектурные решения/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
  });
});
