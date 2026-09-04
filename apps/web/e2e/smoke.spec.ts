import { expect, test } from '@playwright/test';

/**
 * Дымовые сценарии оболочки.
 *
 * Проверяется то, что должно работать без поднятого бэкенда: маршруты, навигация,
 * отсутствие горизонтального скролла и честное поведение при недоступном API.
 * Данные проектов сюда не входят — для них нужна база, и это отдельный прогон.
 */

const horizontalOverflow = () =>
  document.documentElement.scrollWidth - document.documentElement.clientWidth;

test.describe('оболочка портала', () => {
  test('корень ведёт на список проектов', async ({ page }) => {
    await page.goto('/');

    await expect(page).toHaveURL(/\/projects$/);
    await expect(page.getByRole('heading', { name: 'Проекты', level: 1 })).toBeVisible();
  });

  test('нет горизонтального скролла', async ({ page }) => {
    await page.goto('/projects');

    expect(await page.evaluate(horizontalOverflow)).toBeLessThanOrEqual(0);
  });

  test('недоступный API показывает ошибку, а не пустой экран', async ({ page }) => {
    await page.route('**/api/v1/projects*', (route) => route.abort());
    await page.goto('/projects');

    // Ищем внутри main: у Next есть собственный элемент с role="alert" для объявления
    // смены маршрута, и без уточнения селектор попадает в оба.
    // Запрос повторяется один раз, поэтому состояние ошибки появляется не мгновенно.
    await expect(page.getByRole('main').getByRole('alert')).toContainText(
      'Не удалось загрузить проекты',
      { timeout: 15_000 },
    );
  });

  test('разделы следующих этапов видны, но выключены', async ({ page }) => {
    await page.goto('/projects');

    const templates = page.getByLabel(/Шаблоны/);
    await expect(templates).toBeVisible();
    await expect(templates).toHaveAttribute('aria-disabled', 'true');
  });

  test('навигация ведёт в настройки и обратно', async ({ page }) => {
    await page.goto('/projects');

    await page.getByRole('link', { name: 'Настройки' }).click();
    await expect(page).toHaveURL(/\/settings$/);
    await expect(page.getByRole('heading', { name: 'Настройки', level: 1 })).toBeVisible();

    await page.getByRole('link', { name: 'Проекты' }).first().click();
    await expect(page).toHaveURL(/\/projects$/);
  });

  test('создание проекта открывается по кнопке и по адресу', async ({ page }) => {
    await page.goto('/projects');
    await page.getByRole('button', { name: '+ Создать проект' }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(page).toHaveURL(/create=1/);
    // Пока имя не введено, создавать нечего.
    await expect(dialog.getByRole('button', { name: 'Создать проект' })).toBeDisabled();

    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();

    await page.goto('/projects/new');
    await expect(page.getByRole('dialog')).toBeVisible();
  });

  test('диалог объясняет, что будет с каждым типом файла', async ({ page }) => {
    await page.goto('/projects?create=1');
    const dialog = page.getByRole('dialog');

    await expect(dialog.getByText(/ZIP-пакет распознавалки, PDF/)).toBeVisible();
    await dialog.getByRole('textbox').first().fill('Проверочный проект');
    await expect(dialog.getByRole('button', { name: 'Создать проект' })).toBeEnabled();
  });

  test('фокус виден при обходе с клавиатуры', async ({ page }) => {
    await page.goto('/projects');
    await page.keyboard.press('Tab');

    const outline = await page.evaluate(() => {
      const active = document.activeElement;
      return active ? getComputedStyle(active).outlineWidth : '0px';
    });

    expect(outline).not.toBe('0px');
  });
});

test.describe('рабочая область', () => {
  const WORKSPACE = '/projects/11111111-1111-4111-8111-111111111111/workspace';

  test('на десктопе показывает три панели и статусную строку', async ({ page }) => {
    await page.goto(WORKSPACE);

    await expect(page.getByLabel('Панель документов и распознавания')).toBeVisible();
    await expect(page.getByRole('main')).toBeVisible();
    await expect(page.getByLabel('Панель свойств')).toBeVisible();
    // Масштаб чертежа портал определять не умеет и пишет об этом прямо.
    await expect(page.getByText('Масштаб чертежа: Не задан')).toBeVisible();
  });

  test('панели сворачиваются и разворачиваются', async ({ page }) => {
    await page.goto(WORKSPACE);

    await page.getByTitle('Свернуть: Панель документов и распознавания').click();
    await expect(page.getByLabel(/Панель документов.*свёрнута/)).toBeVisible();

    await page.getByTitle(/Развернуть: Панель документов/).click();
    await expect(page.getByLabel('Панель документов и распознавания')).toBeVisible();
  });

  test('вкладка обмеров выключена и подписана этапом', async ({ page }) => {
    await page.goto(WORKSPACE);

    const takeoff = page.getByRole('tab', { name: 'Обмеры' });
    await expect(takeoff).toBeDisabled();
    await expect(takeoff).toHaveAttribute('title', /Этап 2/);
  });

  test('на узком экране показывает требование десктопа', async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 800 });
    await page.goto(WORKSPACE);

    await expect(page.getByRole('heading', { name: 'Нужен экран шире' })).toBeVisible();
    expect(await page.evaluate(horizontalOverflow)).toBeLessThanOrEqual(0);
  });
});
