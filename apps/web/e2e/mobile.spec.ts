import { expect, test } from '@playwright/test';

/**
 * Портал на телефоне.
 *
 * Проверяется то, ради чего делалась адаптивность: ничто не уезжает вбок, разделы
 * доступны снизу, до кнопок можно дотянуться, а рабочая область честно говорит,
 * что ей нужен экран шире, вместо того чтобы ужиматься в нечитаемое.
 *
 * Бэкенд не поднят: сюда входит только оболочка.
 */

const horizontalOverflow = () =>
  document.documentElement.scrollWidth - document.documentElement.clientWidth;

/** Минимальная тап-цель: 44 px по рекомендациям Apple, 48 — по Material. */
const MIN_TAP = 44;

test.describe('телефон', () => {
  test('нет горизонтального скролла на всех страницах оболочки', async ({ page }) => {
    for (const path of ['/projects', '/settings', '/projects?create=1']) {
      await page.goto(path);
      expect(await page.evaluate(horizontalOverflow), path).toBeLessThanOrEqual(0);
    }
  });

  test('предложение обновиться не перекрывает навигацию', async ({ page }) => {
    // Тост об обновлении — фиксированный и поверх всего. Стоя на нижней панели, он
    // забирал себе нажатия по разделам: панель видна, но нажать нельзя.
    await page.goto('/projects');

    const bottom = page.getByRole('navigation', { name: 'Разделы портала' });
    const bar = await bottom.boundingBox();
    expect(bar).not.toBeNull();

    const toast = page.getByRole('status').filter({ hasText: 'Доступна новая версия' });
    if ((await toast.count()) === 0) return;

    const box = await toast.first().boundingBox();
    expect(box).not.toBeNull();
    expect((box?.y ?? 0) + (box?.height ?? 0)).toBeLessThanOrEqual(bar?.y ?? 0);
  });

  test('разделы доступны снизу, а не в боковой рейке', async ({ page }) => {
    await page.goto('/projects');

    const bottom = page.getByRole('navigation', { name: 'Разделы портала' });
    await expect(bottom).toBeVisible();

    await bottom.getByRole('link', { name: 'Настройки' }).click();
    await expect(page).toHaveURL(/\/settings$/);
    await expect(page.getByRole('heading', { name: 'Настройки', level: 1 })).toBeVisible();

    await bottom.getByRole('link', { name: 'Проекты' }).click();
    await expect(page).toHaveURL(/\/projects$/);
  });

  test('до главного действия можно дотянуться и попасть по нему', async ({ page }) => {
    await page.goto('/projects');

    const create = page.getByRole('button', { name: '+ Создать проект' });
    const box = await create.boundingBox();

    expect(box).not.toBeNull();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(MIN_TAP);

    await create.click();
    await expect(page.getByRole('dialog')).toBeVisible();
  });

  test('окно создания проекта помещается в экран', async ({ page }) => {
    await page.goto('/projects?create=1');

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    const box = await dialog.boundingBox();
    const viewport = page.viewportSize();

    expect(box?.width ?? 0).toBeLessThanOrEqual((viewport?.width ?? 0) + 1);
    expect(await page.evaluate(horizontalOverflow)).toBeLessThanOrEqual(0);
  });

  test('поля ввода не вызывают автозум Safari', async ({ page }) => {
    await page.goto('/projects?create=1');

    const input = page.getByRole('dialog').getByRole('textbox');
    await expect(input.first()).toBeVisible();

    // Шрифт мельче 16 px заставляет мобильный Safari зумить форму при фокусе.
    const sizes = await input.evaluateAll((nodes) =>
      nodes.map((node) => parseFloat(getComputedStyle(node).fontSize)),
    );

    expect(sizes.length).toBeGreaterThan(0);
    for (const size of sizes) expect(size).toBeGreaterThanOrEqual(16);
  });

  test('рабочая область честно требует широкий экран', async ({ page }) => {
    await page.goto('/projects/11111111-1111-4111-8111-111111111111/workspace');

    await expect(page.getByRole('heading', { name: 'Нужен экран шире' })).toBeVisible();
    expect(await page.evaluate(horizontalOverflow)).toBeLessThanOrEqual(0);
  });

  test('тема переключается и переживает перезагрузку', async ({ page }) => {
    await page.goto('/settings');

    const before = await page.evaluate(() => document.documentElement.dataset['theme'] ?? null);
    await page.getByRole('button', { name: /Включить (тёмную|светлую) тему/ }).click();

    const after = await page.evaluate(() => document.documentElement.dataset['theme']);
    expect(after).not.toBe(before);

    await page.reload();
    // Тема ставится до первой отрисовки, иначе на загрузке мигает чужая палитра.
    expect(await page.evaluate(() => document.documentElement.dataset['theme'])).toBe(after);
  });
});

/**
 * Телефон: форма и отступы контролов.
 *
 * Правило тап-целей из base.css тянет кнопку до 44px по высоте. Пока служебные
 * классы лежали вне слоёв, явная ширина его не перебивала, и квадратные кнопки
 * превращались в овалы, а нижний отступ окна обнулялся.
 */
test.describe('телефон: контролы', () => {
  test('кнопки окна не прижаты к нижней границе', async ({ page }) => {
    await page.goto('/projects?create=1');

    const dialog = page.getByRole('dialog');
    const submit = dialog.getByRole('button', { name: 'Создать проект' });
    await expect(submit).toBeVisible();

    const card = await dialog.boundingBox();
    const button = await submit.boundingBox();

    const gap = (card?.y ?? 0) + (card?.height ?? 0) - ((button?.y ?? 0) + (button?.height ?? 0));
    expect(gap, 'между кнопкой и краем окна должен быть отступ').toBeGreaterThanOrEqual(12);
  });

  test('квадратная кнопка шапки не вытягивается в овал', async ({ page }) => {
    await page.goto('/projects');

    // Переключатель темы, а не кнопка учётной записи: сеанса в этом прогоне нет,
    // и аватар не отрисовывается. Правило одно и то же — тап-цель тянет кнопку по
    // высоте, и без такой же ширины квадрат превращается в овал.
    const toggle = page.getByRole('button', { name: /Включить (тёмную|светлую) тему/ });
    const box = await toggle.boundingBox();

    expect(box).not.toBeNull();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(MIN_TAP);
    expect(
      Math.abs((box?.width ?? 0) - (box?.height ?? 0)),
      'кнопка должна быть квадратной',
    ).toBeLessThanOrEqual(1);
  });

  test('крестик удаления файла квадратный и не мельче тап-цели', async ({ page }) => {
    await page.goto('/projects?create=1');

    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Выбрать файлы').setInputFiles({
      name: 'чертёж.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.7'),
    });

    const remove = dialog.getByRole('button', { name: /Убрать/ });
    const box = await remove.boundingBox();

    expect(box).not.toBeNull();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(MIN_TAP);
    expect(
      Math.abs((box?.width ?? 0) - (box?.height ?? 0)),
      'крестик должен быть квадратным',
    ).toBeLessThanOrEqual(1);
    expect(await page.evaluate(horizontalOverflow)).toBeLessThanOrEqual(0);
  });

  test('сегменты сортировки не вылезают из дорожки', async ({ page }) => {
    await page.goto('/projects');

    const group = page.getByRole('group', { name: 'Сортировка' });
    const track = await group.boundingBox();
    const segment = await group.getByRole('button').first().boundingBox();

    expect(track).not.toBeNull();
    expect(segment).not.toBeNull();
    expect((segment?.height ?? 0) <= (track?.height ?? 0) + 1, 'сегмент выше дорожки').toBe(true);
  });
});
