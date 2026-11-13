import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { FolderReport, type FolderReportData } from '@/components/projects/FolderReport';

const report = (overrides: Partial<FolderReportData> = {}): FolderReportData => ({
  warnings: [],
  skipped: 0,
  added: 1,
  alreadyInProject: [],
  attachToExisting: [],
  ...overrides,
});

describe('FolderReport', () => {
  it('для комплекта без PDF показывает строку о прикреплении к загруженному PDF', () => {
    render(<FolderReport report={report({ attachToExisting: ['КР1_ver7'] })} />);

    expect(
      screen.getByText('Распознавание прикрепится к загруженному PDF: КР1_ver7.pdf'),
    ).toBeInTheDocument();
  });

  it('предупреждение «Не хватает PDF» подсказывает загрузить PDF отдельно', () => {
    render(
      <FolderReport
        report={report({
          added: 0,
          warnings: [{ stem: 'АР-1', missing: ['АР-1.pdf'] }],
        })}
      />,
    );

    expect(screen.getByText(/Не хватает PDF: АР-1\.pdf/)).toHaveTextContent(
      'или загрузите PDF отдельно, затем выберите папку снова',
    );
  });

  it('без замечаний ничего не показывает', () => {
    const { container } = render(<FolderReport report={report()} />);

    expect(container).toBeEmptyDOMElement();
  });
});
