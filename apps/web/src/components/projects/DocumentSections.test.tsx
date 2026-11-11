import type { DocumentRead } from '@quantor/api-client';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

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

  it('клик по строке выбирает документ, выбранный отмечен', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const { rerender } = render(
      <DocumentSections
        projectId="p-1"
        documents={DOCS}
        revisionsOf={() => null}
        selectedId="3"
        onSelect={onSelect}
      />,
    );

    expect(screen.getByRole('button', { name: 'М-П-ИОС2.1_ver4.pdf' })).toHaveAttribute(
      'aria-current',
      'true',
    );
    expect(screen.getByRole('button', { name: 'М-П-ИОС2.2_ver4.pdf' })).not.toHaveAttribute(
      'aria-current',
    );

    await user.click(screen.getByRole('button', { name: 'М-П-ИОС2.2_ver4.pdf' }));
    expect(onSelect).toHaveBeenCalledWith('4');

    rerender(
      <DocumentSections
        projectId="p-1"
        documents={DOCS}
        revisionsOf={() => null}
        selectedId="4"
        onSelect={onSelect}
      />,
    );
    expect(screen.getByRole('button', { name: 'М-П-ИОС2.2_ver4.pdf' })).toHaveAttribute(
      'aria-current',
      'true',
    );
  });

  it('«Открыть» ведёт в рабочую область и документ не выбирает', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <DocumentSections
        projectId="p-1"
        documents={[DOCS[4] as DocumentRead]}
        revisionsOf={() => ({
          total: 1,
          items: [
            {
              id: 'rev-5',
              document_id: '5',
              revision_label: null,
              source_filename: 'Письмо.pdf',
              source_mime: 'application/pdf',
              source_size: 1000,
              source_sha256: 'a'.repeat(64),
              processing_status: 'unprocessed',
              processing_error_code: null,
              geometry_status: 'ready',
              geometry_error_code: null,
              sheet_count: 1,
              source_metadata: {},
              created_at: '2026-09-01T10:00:00Z',
            },
          ],
        })}
        onSelect={onSelect}
      />,
    );

    const open = screen.getByRole('link', { name: 'Открыть Письмо.pdf' });
    expect(open).toHaveAttribute('href', '/projects/p-1/workspace?revision=rev-5');
    open.addEventListener('click', (event) => event.preventDefault());
    await user.click(open);
    expect(onSelect).not.toHaveBeenCalled();
  });

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
