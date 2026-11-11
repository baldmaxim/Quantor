import * as client from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { passportRow } from './__fixtures__';
import { SheetPassportEditDialog } from './SheetPassportEditDialog';

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  patchSheetPassport: vi.fn(),
}));

const mount = (onClose = vi.fn()) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <SheetPassportEditDialog
        projectId="p-1"
        row={passportRow({ section: null })}
        marks={['АР', 'КР']}
        onClose={onClose}
      />
    </QueryClientProvider>,
  );
  return onClose;
};

describe('Правка листа', () => {
  beforeEach(() => {
    vi.mocked(client.patchSheetPassport)
      .mockReset()
      .mockImplementation((() => Promise.resolve({ data: passportRow() })) as never);
  });

  it('без изменений «Сохранить» недоступна', () => {
    mount();
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled();
  });

  it('уходят только изменённые поля', async () => {
    const onClose = mount();
    await userEvent.selectOptions(screen.getByLabelText('Раздел'), 'КР');
    await userEvent.selectOptions(screen.getByLabelText('Тип листа'), 'section');
    await userEvent.type(screen.getByLabelText('Секция'), '2');
    await userEvent.clear(screen.getByLabelText('Отметка, м'));
    await userEvent.type(screen.getByLabelText('Отметка, м'), '-3,2');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(client.patchSheetPassport).toHaveBeenCalledTimes(1));
    expect(client.patchSheetPassport).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { project_id: 'p-1', passport_id: 'sp-1' },
        body: { section_mark: 'КР', sheet_kind: 'section', section: '2', elevation_m: -3.2 },
      }),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('очищенное поле уходит как null', async () => {
    mount();
    await userEvent.click(screen.getByRole('button', { name: 'Очистить: Заголовок' }));
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(client.patchSheetPassport).toHaveBeenCalled());
    expect(vi.mocked(client.patchSheetPassport).mock.calls[0]?.[0]?.body).toEqual({ title: null });
  });

  it('отметка не числом блокирует сохранение', async () => {
    mount();
    await userEvent.type(screen.getByLabelText('Отметка, м'), 'x');
    expect(screen.getByText('Отметка должна быть числом')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled();
  });
});
