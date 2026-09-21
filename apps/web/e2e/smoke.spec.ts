import { expect, test, type Page } from '@playwright/test';

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

  test.describe('пилот ручного обмера', () => {
    // Первая версия сценария с включённым пилотом падала через раз, и не из-за теста: если
    // `meta` приходила раньше, чем гидрировалась страница, вкладка оставалась выключенной
    // навсегда. Причина и защита — в `useFeatures` (features-hydration.test.tsx); сценарий
    // проверен десятью повторами на обоих разрешениях.
    test('вкладка обмеров открывает список строк, когда пилот включён', async ({ page }) => {
      // Была выключена и подписана «Этап 2» до Stage 2A, затем включена жёстко. Теперь ручной
      // обмер — пилотная возможность, и вкладку открывает флаг пространства (ADR-0023): тест
      // переписан осознанно и проверяет именно это поведение.
      await page.route('**/api/v1/meta*', (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            api_version: '1.0.0',
            schema_version: 10,
            environment: 'test',
            stage: 'stage-2b',
            features: { viewer: true, 'takeoff.manual': true },
            auth_mode: 'dev',
          }),
        }),
      );
      await page.goto(WORKSPACE);

      const takeoff = page.getByRole('tab', { name: 'Обмеры' });
      await expect(takeoff).toBeEnabled();

      await takeoff.click();
      await expect(page.getByText('Строк обмера нет')).toBeVisible();
    });

    test('без пилота вкладка обмеров выключена и объясняет почему', async ({ page }) => {
      // Без бэкенда флагов нет, а отсутствие флага — это «выключено», а не «включено».
      await page.goto(WORKSPACE);

      const takeoff = page.getByRole('tab', { name: 'Обмеры' });
      await expect(takeoff).toBeDisabled();
      await expect(takeoff).toHaveAttribute('title', /пилот/);
    });
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

test.describe('карточка проекта', () => {
  const PROJECT_ID = '22222222-2222-4222-8222-222222222222';
  const DOCUMENT_ID = '33333333-3333-4333-8333-333333333333';
  const REVISION_ID = '44444444-4444-4444-8444-444444444444';

  /**
   * Обычный PDF: распознавание к нему не применяли и не применят. До промта 01 карточка
   * требовала `processing_status=ready`, и такой документ не открывался никогда.
   */
  const revision = (overrides: Record<string, unknown> = {}) => ({
    id: REVISION_ID,
    document_id: DOCUMENT_ID,
    revision_label: null,
    source_filename: 'План 3 этажа.pdf',
    source_mime: 'application/pdf',
    source_size: 2_400_000,
    source_sha256: 'a'.repeat(64),
    processing_status: 'unprocessed',
    processing_error_code: null,
    geometry_status: 'ready',
    geometry_error_code: null,
    sheet_count: 2,
    source_metadata: {},
    created_at: '2026-09-01T10:00:00Z',
    ...overrides,
  });

  const mockProject = async (page: Page, revisions: Record<string, unknown>[]) => {
    const json = (body: unknown) => ({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });

    await page.route(`**/api/v1/projects/${PROJECT_ID}`, (route) =>
      route.fulfill(
        json({
          id: PROJECT_ID,
          name: 'Обычный PDF',
          status: 'active',
          source: 'manual',
          external_ref: null,
          created_at: '2026-09-01T10:00:00Z',
          updated_at: '2026-09-01T10:00:00Z',
          document_count: 1,
          sheet_count: 2,
          last_job: null,
        }),
      ),
    );

    await page.route(`**/api/v1/projects/${PROJECT_ID}/documents*`, (route) =>
      route.fulfill(
        json({
          items: [
            {
              id: DOCUMENT_ID,
              project_id: PROJECT_ID,
              display_name: 'План 3 этажа.pdf',
              discipline: null,
              document_kind: 'pdf',
              created_at: '2026-09-01T10:00:00Z',
              updated_at: '2026-09-01T10:00:00Z',
            },
          ],
          total: 1,
          limit: 200,
          offset: 0,
        }),
      ),
    );

    await page.route(`**/api/v1/documents/${DOCUMENT_ID}/revisions*`, (route) =>
      route.fulfill(json({ items: revisions, total: revisions.length, limit: 50, offset: 0 })),
    );
  };

  test('нераспознанный PDF с готовыми листами открывается', async ({ page }) => {
    await mockProject(page, [revision()]);
    await page.goto(`/projects/${PROJECT_ID}`);

    const top = page.getByRole('link', { name: 'Открыть рабочую область' });
    await expect(top).toHaveAttribute(
      'href',
      `/projects/${PROJECT_ID}/workspace?revision=${REVISION_ID}`,
    );

    // Действие есть и у самой строки документа: документов в проекте бывает несколько.
    await expect(page.getByRole('link', { name: /Открыть План 3 этажа/ })).toBeVisible();
    await expect(page.getByText('Листы готовы')).toBeVisible();
    await expect(page.getByText('Не распознан')).toBeVisible();
  });

  test('пока листы готовятся, кнопка неактивна и объясняет почему', async ({ page }) => {
    await mockProject(page, [revision({ geometry_status: 'pending', sheet_count: 0 })]);
    await page.goto(`/projects/${PROJECT_ID}`);

    const button = page.getByRole('button', { name: 'Открыть рабочую область' });
    await expect(button).toBeDisabled();
    await expect(button).toHaveAttribute('title', /Готовим листы/);
    // Распознанный пакет больше не требуется ни в одном тексте карточки.
    await expect(page.getByText('Нужен распознанный PDF')).toHaveCount(0);
  });
});

/**
 * Геометрия модального окна.
 *
 * Отдельным блоком, потому что проверяется не поведение, а расстояния: ряд кнопок
 * лежал вплотную к нижней границе окна — служебный класс безопасной зоны стоял вне
 * слоёв CSS и обнулял нижний отступ, заданный разметкой.
 *
 * Пока окно открыто, фон помечен inert, поэтому искать в нём нечего: все запросы
 * идут внутрь getByRole('dialog').
 */
test.describe('модальное окно', () => {
  test('кнопки не прижаты к нижней границе', async ({ page }) => {
    await page.goto('/projects?create=1');

    const dialog = page.getByRole('dialog');
    const submit = dialog.getByRole('button', { name: 'Создать проект' });
    await expect(submit).toBeVisible();

    const card = await dialog.boundingBox();
    const button = await submit.boundingBox();
    expect(card).not.toBeNull();
    expect(button).not.toBeNull();

    const gap = (card?.y ?? 0) + (card?.height ?? 0) - ((button?.y ?? 0) + (button?.height ?? 0));
    // На десктопе безопасной зоны нет, поэтому это чистый отступ карточки.
    expect(gap, 'между кнопкой и краем окна должен быть отступ').toBeGreaterThanOrEqual(16);
  });

  test('страница под окном недоступна с клавиатуры', async ({ page }) => {
    await page.goto('/projects?create=1');
    await expect(page.getByRole('dialog')).toBeVisible();

    for (let step = 0; step < 12; step += 1) {
      await page.keyboard.press('Tab');
      const inside = await page.evaluate(
        () => document.activeElement?.closest('[role="dialog"]') !== null,
      );
      expect(inside, `после ${step + 1} нажатий Tab фокус ушёл на страницу`).toBe(true);
    }
  });

  test('фокус возвращается на кнопку, которой открыли окно', async ({ page }) => {
    await page.goto('/projects');

    const trigger = page.getByRole('button', { name: '+ Создать проект' });
    await trigger.click();
    await expect(page.getByRole('dialog')).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toBeHidden();

    // Иначе после закрытия обход начинается сначала, и место в интерфейсе теряется.
    await expect(trigger).toBeFocused();
  });
});
