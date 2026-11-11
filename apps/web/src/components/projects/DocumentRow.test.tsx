import type { DocumentRead, DocumentRevisionRead } from '@quantor/api-client';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { DocumentRow } from './DocumentRow';

/**
 * Строка документа.
 *
 * Проверяется то, ради чего строка переделана: обычный PDF получает действие «Открыть» и
 * без распознавания, а неготовый документ честно говорит, что с ним происходит.
 */

const pdf = (overrides: Partial<DocumentRead> = {}): DocumentRead => ({
  id: 'doc-1',
  project_id: 'p-1',
  display_name: 'План 3 этажа.pdf',
  discipline: null,
  document_kind: 'pdf',
  created_at: '2026-09-01T10:00:00Z',
  updated_at: '2026-09-01T10:00:00Z',
  ...overrides,
});

const revision = (overrides: Partial<DocumentRevisionRead> = {}): DocumentRevisionRead => ({
  id: 'rev-1',
  document_id: 'doc-1',
  revision_label: null,
  source_filename: 'План 3 этажа.pdf',
  source_mime: 'application/pdf',
  source_size: 2_400_000,
  source_sha256: 'a'.repeat(64),
  processing_status: 'unprocessed',
  processing_error_code: null,
  geometry_status: 'ready',
  geometry_error_code: null,
  sheet_count: 4,
  source_metadata: {},
  created_at: '2026-09-01T10:00:00Z',
  ...overrides,
});

describe('строка документа', () => {
  it('нераспознанный PDF с готовыми листами открывается', () => {
    render(<DocumentRow projectId="p-1" document={pdf()} revisions={[revision()]} total={1} />);

    expect(screen.getByRole('link', { name: 'Открыть План 3 этажа.pdf' })).toHaveAttribute(
      'href',
      '/projects/p-1/workspace?revision=rev-1',
    );
    // Оба состояния рядом и не подменяют друг друга.
    expect(screen.getByText('Листы готовы')).toBeInTheDocument();
    expect(screen.getByText('Не распознан')).toBeInTheDocument();
    expect(screen.getByText(/4 листа/)).toBeInTheDocument();
  });

  it('ведёт на последнюю открываемую ревизию', () => {
    const revisions = [
      revision({ id: 'rev-1' }),
      revision({ id: 'rev-2' }),
      revision({ id: 'rev-3', geometry_status: 'pending', sheet_count: 0 }),
    ];

    render(<DocumentRow projectId="p-1" document={pdf()} revisions={revisions} total={3} />);

    expect(screen.getByRole('link', { name: /Открыть/ })).toHaveAttribute(
      'href',
      '/projects/p-1/workspace?revision=rev-2',
    );
    expect(screen.getByText(/ревизий: 3/)).toBeInTheDocument();
  });

  it('пока листы готовятся, открыть не предлагает', () => {
    render(
      <DocumentRow
        projectId="p-1"
        document={pdf()}
        revisions={[revision({ geometry_status: 'pending', sheet_count: 0 })]}
        total={1}
      />,
    );

    expect(screen.queryByRole('link', { name: /Открыть/ })).not.toBeInTheDocument();
    expect(screen.getByText('Подготавливаем листы')).toBeInTheDocument();
  });

  it('неудачную подготовку не прячет и называет причину', () => {
    render(
      <DocumentRow
        projectId="p-1"
        document={pdf()}
        revisions={[
          revision({
            geometry_status: 'failed',
            geometry_error_code: 'PDF_UNREADABLE',
            sheet_count: 0,
          }),
        ]}
        total={1}
      />,
    );

    expect(screen.getByText('Листы не подготовлены')).toBeInTheDocument();
    expect(screen.getByText(/Листы подготовить не удалось/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Открыть/ })).not.toBeInTheDocument();
  });

  it('распознанный пакет остаётся с прежним поведением и без состояния листов', () => {
    const archive = pdf({ document_kind: 'recognized_package', display_name: 'пакет.zip' });

    render(
      <DocumentRow
        projectId="p-1"
        document={archive}
        revisions={[revision({ processing_status: 'ready' })]}
        total={1}
      />,
    );

    expect(screen.getByText('Готов')).toBeInTheDocument();
    expect(screen.queryByText('Листы готовы')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Открыть/ })).not.toBeInTheDocument();
  });

  it('пока ревизии не загружены, состояние не выдумывается', () => {
    render(<DocumentRow projectId="p-1" document={pdf()} revisions={null} total={0} />);

    expect(screen.queryByRole('link', { name: /Открыть/ })).not.toBeInTheDocument();
    expect(screen.queryByText('Не распознан')).not.toBeInTheDocument();
  });

  it('имя файла — кнопка выбора, растянутая на всю строку; ссылкой не является', () => {
    render(<DocumentRow projectId="p-1" document={pdf()} revisions={[revision()]} total={1} />);

    const name = screen.getByRole('button', { name: 'План 3 этажа.pdf' });

    expect(screen.queryByRole('link', { name: 'План 3 этажа.pdf' })).not.toBeInTheDocument();
    // Псевдоэлемент на всю строку: строка — контейнер позиционирования.
    expect(name.className).toContain('after:absolute');
    expect(name.className).toContain('after:inset-0');
    expect(name.closest('div.relative')).not.toBeNull();
  });

  it('клик и клавиатура выбирают документ, не уходя со страницы', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <DocumentRow
        projectId="p-1"
        document={pdf()}
        revisions={[revision()]}
        total={1}
        onSelect={onSelect}
      />,
    );

    const name = screen.getByRole('button', { name: 'План 3 этажа.pdf' });
    await user.click(name);
    expect(onSelect).toHaveBeenLastCalledWith('doc-1');

    name.focus();
    await user.keyboard('{Enter}');
    await user.keyboard(' ');
    expect(onSelect).toHaveBeenCalledTimes(3);
  });

  it('«Открыть» ведёт в рабочую область и документ не выбирает', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <DocumentRow
        projectId="p-1"
        document={pdf()}
        revisions={[revision()]}
        total={1}
        onSelect={onSelect}
      />,
    );

    const open = screen.getByRole('link', { name: 'Открыть План 3 этажа.pdf' });
    expect(open).toHaveAttribute('href', '/projects/p-1/workspace?revision=rev-1');
    // Ссылка лежит поверх растянутой кнопки.
    expect(open.className).toContain('relative');
    expect(open.className).toContain('z-10');

    open.addEventListener('click', (event) => event.preventDefault());
    await user.click(open);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('выбранная строка отмечена aria-current и подсвечена токеном', () => {
    const { rerender } = render(
      <DocumentRow projectId="p-1" document={pdf()} revisions={[revision()]} total={1} />,
    );
    const name = () => screen.getByRole('button', { name: 'План 3 этажа.pdf' });
    expect(name()).not.toHaveAttribute('aria-current');

    rerender(
      <DocumentRow projectId="p-1" document={pdf()} revisions={[revision()]} total={1} selected />,
    );
    expect(name()).toHaveAttribute('aria-current', 'true');
    expect(name().closest('div.relative')?.className).toContain('bg-accent-soft');
  });

  it('строка без возможности открытия не содержит ссылок, но выбирается', () => {
    render(
      <DocumentRow
        projectId="p-1"
        document={pdf()}
        revisions={[revision({ geometry_status: 'pending', sheet_count: 0 })]}
        total={1}
      />,
    );

    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByText('План 3 этажа.pdf')).toBeInTheDocument();
  });
});
