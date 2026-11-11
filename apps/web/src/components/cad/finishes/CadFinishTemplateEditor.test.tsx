import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  createCadFinishTemplate: vi.fn(),
  updateCadFinishTemplate: vi.fn(),
  listCadFinishTemplates: vi.fn(),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));

import { CadFinishTemplateEditor } from './CadFinishTemplateEditor';
import { templateFixture } from './finish-fixtures';

const renderEditor = (props: Partial<Parameters<typeof CadFinishTemplateEditor>[0]> = {}) => {
  const onClose = vi.fn();
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <CadFinishTemplateEditor
        projectId="p1"
        template={null}
        templates={[]}
        onClose={onClose}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { onClose };
};

const typeInto = (name: string, value: string) =>
  fireEvent.change(screen.getByRole('textbox', { name }), { target: { value } });

describe('редактор шаблона отделки', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listCadFinishTemplates.mockResolvedValue({ data: [] });
  });

  it('заготовка «Черновая МОП» подставляет слои трёх поверхностей без чисел', () => {
    renderEditor();
    fireEvent.click(screen.getByRole('button', { name: 'Черновая МОП' }));
    expect(screen.getByRole('group', { name: 'Пол, слой 3' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Стены, слой 5' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Потолок, слой 4' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Работа: Пол, слой 3' })).toHaveValue('Стяжка');
    expect(screen.getByRole('textbox', { name: 'Раз: Стены, слой 5' })).toHaveValue('2');
    expect(screen.getByRole('textbox', { name: 'Расход: Пол, слой 3' })).toHaveValue('');
    expect(screen.getByRole('textbox', { name: 'Толщина, мм: Пол, слой 3' })).toHaveValue('');
  });

  it('заготовка «Черновая МОП»: чипы оснований у слоёв стен', () => {
    renderEditor();
    fireEvent.click(screen.getByRole('button', { name: 'Черновая МОП' }));
    const checked = (base: string, layer: number) =>
      screen.getByRole('checkbox', { name: `${base}: Стены, слой ${layer}` });
    // слой 1 - обеспыливание: только монолит
    expect(checked('Монолит', 1)).toBeChecked();
    expect(checked('Кладка', 1)).not.toBeChecked();
    expect(checked('ГКЛ', 1)).not.toBeChecked();
    // слой 3 - штукатурка: монолит и кладка
    expect(checked('Монолит', 3)).toBeChecked();
    expect(checked('Кладка', 3)).toBeChecked();
    expect(checked('ГКЛ', 3)).not.toBeChecked();
    // слой 2 - грунтовка: все основания (ни одного отмеченного)
    expect(checked('Монолит', 2)).not.toBeChecked();
    // у пола и потолка оснований нет
    expect(screen.queryByRole('checkbox', { name: 'Монолит: Пол, слой 1' })).toBeNull();
    expect(screen.queryByRole('checkbox', { name: 'Монолит: Потолок, слой 1' })).toBeNull();
  });

  it('основания и флажок откосов уходят в теле POST', async () => {
    api.createCadFinishTemplate.mockResolvedValue({ data: templateFixture() });
    const { onClose } = renderEditor();
    typeInto('Название шаблона', 'Стены');
    fireEvent.click(screen.getByRole('checkbox', { name: 'Включать откосы дверей в стены' }));
    fireEvent.click(screen.getByRole('button', { name: 'Добавить слой: Стены' }));
    typeInto('Работа: Стены, слой 1', 'Штукатурка');
    fireEvent.click(screen.getByRole('checkbox', { name: 'Кладка: Стены, слой 1' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Монолит: Стены, слой 1' }));
    fireEvent.click(screen.getByRole('button', { name: 'Добавить слой: Стены' }));
    typeInto('Работа: Стены, слой 2', 'Окраска');
    for (const base of ['Монолит', 'Кладка', 'ГКЛ']) {
      fireEvent.click(screen.getByRole('checkbox', { name: `${base}: Стены, слой 2` }));
    }
    fireEvent.click(screen.getByRole('button', { name: 'Создать шаблон' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const body = api.createCadFinishTemplate.mock.calls[0]?.[0]?.body;
    expect(body).toMatchObject({ walls_include_reveals: true });
    expect(body.wall_layers.map((layer: { bases: unknown }) => layer.bases)).toEqual([
      ['monolith', 'masonry'],
      null,
    ]);
  });

  it('флажок откосов в новом шаблоне по умолчанию снят', async () => {
    renderEditor();
    expect(
      screen.getByRole('checkbox', { name: 'Включать откосы дверей в стены' }),
    ).not.toBeChecked();
  });

  it('правка шаблона: флажок и основания из шаблона, PATCH передаёт их', async () => {
    const template = templateFixture({
      id: 't7',
      walls_include_reveals: true,
      wall_layers: [{ work: 'Обеспыливание', bases: ['monolith'] }],
    });
    api.updateCadFinishTemplate.mockResolvedValue({ data: template });
    const { onClose } = renderEditor({ template, templates: [template] });
    expect(screen.getByRole('checkbox', { name: 'Включать откосы дверей в стены' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Монолит: Стены, слой 1' })).toBeChecked();
    fireEvent.click(screen.getByRole('checkbox', { name: 'ГКЛ: Стены, слой 1' }));
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(api.updateCadFinishTemplate.mock.calls[0]?.[0]?.body).toMatchObject({
      walls_include_reveals: true,
      wall_layers: [{ work: 'Обеспыливание', bases: ['monolith', 'gkl'] }],
    });
  });

  it('создание: POST с телом черновика, успех закрывает форму', async () => {
    api.createCadFinishTemplate.mockResolvedValue({ data: templateFixture() });
    const { onClose } = renderEditor();
    typeInto('Название шаблона', 'Холлы');
    fireEvent.click(screen.getByRole('checkbox', { name: 'Лифтовой холл' }));
    typeInto('Высота стен, мм', '2700');
    fireEvent.click(screen.getByRole('button', { name: 'Добавить слой: Пол' }));
    typeInto('Работа: Пол, слой 1', 'Стяжка');
    typeInto('Толщина, мм: Пол, слой 1', '50');
    typeInto('Расход: Пол, слой 1', '1,8');
    typeInto('Единица расхода: Пол, слой 1', 'кг');
    fireEvent.click(screen.getByRole('checkbox', { name: 'Расход на мм: Пол, слой 1' }));
    fireEvent.click(screen.getByRole('button', { name: 'Создать шаблон' }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(api.createCadFinishTemplate).toHaveBeenCalledTimes(1);
    expect(api.createCadFinishTemplate.mock.calls[0]?.[0]).toMatchObject({
      path: { project_id: 'p1' },
      body: {
        name: 'Холлы',
        room_types: ['lift_hall'],
        wall_height_mm: 2700,
        floor_layers: [
          {
            work: 'Стяжка',
            material: null,
            coats: 1,
            thickness_mm: 50,
            consumption: 1.8,
            consumption_unit: 'кг',
            consumption_per_mm: true,
          },
        ],
        wall_layers: [],
        ceiling_layers: [],
      },
    });
  });

  it('без названия запрос не уходит, ошибка у поля', () => {
    renderEditor();
    fireEvent.click(screen.getByRole('button', { name: 'Создать шаблон' }));
    expect(screen.getByText('Укажите название шаблона')).toBeInTheDocument();
    expect(api.createCadFinishTemplate).not.toHaveBeenCalled();
  });

  it('слой без работы и расход без единицы - ошибки у полей слоя', () => {
    renderEditor();
    typeInto('Название шаблона', 'А');
    fireEvent.click(screen.getByRole('button', { name: 'Добавить слой: Пол' }));
    typeInto('Расход: Пол, слой 1', '2');
    fireEvent.click(screen.getByRole('button', { name: 'Создать шаблон' }));
    expect(screen.getByText('Укажите работу')).toBeInTheDocument();
    expect(screen.getByText('Укажите единицу расхода')).toBeInTheDocument();
    expect(api.createCadFinishTemplate).not.toHaveBeenCalled();
  });

  it('409: название занято - текст у поля названия, форма остаётся', async () => {
    api.createCadFinishTemplate.mockRejectedValue({
      detail: { code: 'CAD_FINISH_TEMPLATE_NAME_TAKEN', message: 'x' },
    });
    const { onClose } = renderEditor();
    typeInto('Название шаблона', 'Занято');
    fireEvent.click(screen.getByRole('button', { name: 'Создать шаблон' }));
    expect(
      await screen.findByText('Шаблон с таким названием уже есть в проекте.'),
    ).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('409: тип помещения занят - текст у блока типов', async () => {
    api.createCadFinishTemplate.mockRejectedValue({
      detail: { code: 'CAD_FINISH_ROOM_TYPE_TAKEN', message: 'x' },
    });
    renderEditor();
    typeInto('Название шаблона', 'А');
    fireEvent.click(screen.getByRole('button', { name: 'Создать шаблон' }));
    expect(
      await screen.findByText('Один из типов помещений уже назначен другому шаблону.'),
    ).toBeInTheDocument();
  });

  it('тип помещения другого шаблона неактивен с подписью шаблона', () => {
    renderEditor({ templates: [templateFixture({ id: 'other', name: 'Коридоры' })] });
    const taken = screen.getByRole('checkbox', { name: /Коридор/ });
    expect(taken).toBeDisabled();
    expect(taken.closest('label')).toHaveTextContent('в шаблоне «Коридоры»');
    expect(screen.getByRole('checkbox', { name: 'Лифтовой холл' })).toBeEnabled();
  });

  it('правка: PATCH по id; собственные типы шаблона активны, пустая высота - null', async () => {
    const template = templateFixture({ id: 't9', room_types: ['stair'], wall_height_mm: 2700 });
    api.updateCadFinishTemplate.mockResolvedValue({ data: template });
    const { onClose } = renderEditor({ template, templates: [template] });
    expect(screen.getByRole('checkbox', { name: 'Лестничная клетка' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Лестничная клетка' })).toBeEnabled();
    typeInto('Высота стен, мм', '');
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(api.updateCadFinishTemplate.mock.calls[0]?.[0]).toMatchObject({
      path: { project_id: 'p1', template_id: 't9' },
      body: { name: 'Черновая МОП', room_types: ['stair'], wall_height_mm: null },
    });
  });

  it('слои: вверх, вниз, удалить; не больше 20', () => {
    renderEditor();
    fireEvent.click(screen.getByRole('button', { name: 'Черновая квартира' }));
    // пол: Грунтовка, Стяжка
    fireEvent.click(screen.getByRole('button', { name: 'Вверх: Пол, слой 2' }));
    expect(screen.getByRole('textbox', { name: 'Работа: Пол, слой 1' })).toHaveValue('Стяжка');
    fireEvent.click(screen.getByRole('button', { name: 'Удалить: Пол, слой 1' }));
    const floor = screen.getByRole('group', { name: 'Пол, слой 1' });
    expect(within(floor).getByRole('textbox', { name: 'Работа: Пол, слой 1' })).toHaveValue(
      'Грунтовка',
    );
    expect(screen.queryByRole('group', { name: 'Пол, слой 2' })).toBeNull();
  });
});
