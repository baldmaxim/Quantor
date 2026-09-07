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
