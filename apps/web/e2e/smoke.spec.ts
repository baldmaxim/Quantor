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

  test('счётчик проектов виден в шапке', async ({ page }) => {
    // Счётчик живёт в шапке, а не в теле страницы: заголовок раздела там уже есть,
    // и дублировать его ради подписи незачем. Регрессия: свойство однажды потерялось
    // при правке, и на десктопе счётчик просто исчез.
    await page.route('**/api/v1/projects*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            {
              id: '11111111-1111-4111-8111-111111111111',
              name: 'Проверочный проект',
              status: 'active',
              source: 'manual',
              external_ref: null,
              created_at: '2026-09-01T10:00:00Z',
              updated_at: '2026-09-04T08:42:00Z',
              document_count: 2,
              sheet_count: 77,
              last_job: null,
            },
          ],
          total: 1,
          limit: 50,
          offset: 0,
        }),
      }),
    );

    await page.goto('/projects');

    const header = page.getByRole('banner');
    await expect(header).toContainText('1 проект');
    await expect(header).toContainText('2 документа');
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

  test('вкладка обмеров открывает список строк', async ({ page }) => {
    // Была выключена и подписана «Этап 2» до Stage 2A. Теперь ручной обмер существует,
    // и тест переписан осознанно, а не подогнан: он проверяет новое поведение.
    await page.goto(WORKSPACE);

    const takeoff = page.getByRole('tab', { name: 'Обмеры' });
    await expect(takeoff).toBeEnabled();

    await takeoff.click();
    await expect(page.getByText('Строк обмера нет')).toBeVisible();
  });

  test('без ревизии объясняет, что открывать нечего', async ({ page }) => {
    await page.goto(WORKSPACE);

    await expect(page.getByText('Ревизия не выбрана')).toBeVisible();
  });

  test('pdf.js не грузится вне рабочей области', async ({ page }) => {
    // Требование этапа: тяжёлые зависимости просмотрщика не должны попадать в бандл
    // списка проектов. Проверяем по фактически загруженным скриптам, а не по конфигу.
    const scripts: string[] = [];
    page.on('response', (response) => {
      const url = response.url();
      if (url.endsWith('.js')) scripts.push(url);
    });

    await page.goto('/projects');
    await page.waitForLoadState('networkidle');

    const sizes = await Promise.all(
      scripts.map(async (url) => {
        const response = await page.request.get(url);
        const body = await response.text();
        return body.includes('PDFDocumentProxy') || body.includes('pdfjs') ? url : null;
      }),
    );

    expect(sizes.filter(Boolean)).toHaveLength(0);
  });

  test('на узком экране показывает требование десктопа', async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 800 });
    await page.goto(WORKSPACE);

    await expect(page.getByRole('heading', { name: 'Нужен экран шире' })).toBeVisible();
    expect(await page.evaluate(horizontalOverflow)).toBeLessThanOrEqual(0);
  });
});
