import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useWorkspaceStore } from '@/store/workspace';

import { pipelineOfSheet, pipelineSheet, stage } from './pipeline-fixtures';
import { WorkspacePipelineBadge } from './WorkspacePipelineBadge';

describe('WorkspacePipelineBadge', () => {
  beforeEach(() => useWorkspaceStore.setState({ mode: 'sheets' }));

  it('итог листа: подпись и aria-label', () => {
    render(
      <WorkspacePipelineBadge pipeline={pipelineOfSheet(pipelineSheet())} cadOn onOpen={vi.fn()} />,
    );
    expect(screen.getByRole('button', { name: 'Обработка листа: Ждёт одобрения' })).toHaveTextContent(
      'Ждёт одобрения',
    );
  });

  it('ошибка этапа - в подписи', () => {
    const sheet = pipelineSheet({ convert: stage({ status: 'failed' }), views: [] });
    render(<WorkspacePipelineBadge pipeline={pipelineOfSheet(sheet)} cadOn onOpen={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Обработка листа: Ошибка: CAD' })).toBeInTheDocument();
  });

  it('лист не в конвейере: «Лист не обрабатывался»', () => {
    render(<WorkspacePipelineBadge pipeline={pipelineOfSheet(null)} cadOn onOpen={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Обработка листа: Лист не обрабатывался' })).toBeInTheDocument();
  });

  it('загрузка: ничего', () => {
    const { container } = render(
      <WorkspacePipelineBadge pipeline={pipelineOfSheet(null, { isPending: true })} cadOn onOpen={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('без cad.export: ничего', () => {
    const { container } = render(
      <WorkspacePipelineBadge pipeline={pipelineOfSheet(pipelineSheet())} cadOn={false} onOpen={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('нажатие включает режим CAD и открывает «Обработку»', () => {
    const onOpen = vi.fn();
    render(<WorkspacePipelineBadge pipeline={pipelineOfSheet(pipelineSheet())} cadOn onOpen={onOpen} />);
    fireEvent.click(screen.getByRole('button'));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(useWorkspaceStore.getState().mode).toBe('cad');
  });
});
