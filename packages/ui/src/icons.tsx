/**
 * Иконки интерфейса.
 *
 * Собственные, а не библиотека: их немного, они одного веса и стиля, и тянуть ради
 * десятка глифов пакет на несколько тысяч иконок незачем.
 *
 * Все — линейные, наследуют цвет текста и не содержат заливок: цвет задаётся классом,
 * а не внутри файла.
 */

import type { SVGProps } from 'react';

type IconProps = SVGProps<SVGSVGElement>;

const Base = ({ children, ...rest }: IconProps) => (
  <svg
    aria-hidden="true"
    viewBox="0 0 24 24"
    width="18"
    height="18"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
    strokeLinejoin="round"
    {...rest}
  >
    {children}
  </svg>
);

export const IconProjects = (props: IconProps) => (
  <Base {...props}>
    <path d="M3 7h6l2 2h10v10H3z" />
  </Base>
);

export const IconTemplates = (props: IconProps) => (
  <Base {...props}>
    <path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z" />
  </Base>
);

export const IconModels = (props: IconProps) => (
  <Base {...props}>
    <path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z" />
    <path d="M12 12l8-4.5M12 12v9M12 12L4 7.5" />
  </Base>
);

export const IconReports = (props: IconProps) => (
  <Base {...props}>
    <path d="M6 3h9l5 5v13H6z" />
    <path d="M9 13h6M9 17h4" />
  </Base>
);

export const IconSettings = (props: IconProps) => (
  <Base {...props}>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2" />
  </Base>
);

export const IconPdf = (props: IconProps) => (
  <Base {...props}>
    <path d="M6 3h9l5 5v13H6z" />
    <path d="M15 3v5h5" />
  </Base>
);

export const IconZip = (props: IconProps) => (
  <Base {...props}>
    <path d="M6 3h12v18H6z" />
    <path d="M11 3v3M13 6v3M11 9v3M13 12v3" />
  </Base>
);

export const IconBim = (props: IconProps) => (
  <Base {...props}>
    <path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z" />
    <path d="M12 12l8-4.5M12 12v9M12 12L4 7.5" />
  </Base>
);

export const IconChevronLeft = (props: IconProps) => (
  <Base {...props}>
    <path d="M15 6l-6 6 6 6" />
  </Base>
);

export const IconChevronRight = (props: IconProps) => (
  <Base {...props}>
    <path d="M9 6l6 6-6 6" />
  </Base>
);

export const IconCursor = (props: IconProps) => (
  <Base {...props}>
    <path d="M6 3l12 8-5 1.4L10.6 18z" />
  </Base>
);

export const IconHand = (props: IconProps) => (
  <Base {...props}>
    <path d="M9 11V6a1.5 1.5 0 013 0v5M12 11V5a1.5 1.5 0 013 0v6M15 11V7a1.5 1.5 0 013 0v7a6 6 0 01-6 6h-1a6 6 0 01-6-6v-3a1.5 1.5 0 013 0" />
  </Base>
);

export const IconZoomIn = (props: IconProps) => (
  <Base {...props}>
    <circle cx="11" cy="11" r="7" />
    <path d="M8 11h6M11 8v6M20 20l-3.5-3.5" />
  </Base>
);

export const IconZoomOut = (props: IconProps) => (
  <Base {...props}>
    <circle cx="11" cy="11" r="7" />
    <path d="M8 11h6M20 20l-3.5-3.5" />
  </Base>
);

export const IconLayers = (props: IconProps) => (
  <Base {...props}>
    <path d="M12 3l9 5-9 5-9-5z" />
    <path d="M3 13l9 5 9-5" />
  </Base>
);

export const IconReset = (props: IconProps) => (
  <Base {...props}>
    <path d="M4 9a8 8 0 1114 5" />
    <path d="M4 4v5h5" />
  </Base>
);

export const IconEye = (props: IconProps) => (
  <Base {...props}>
    <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z" />
    <circle cx="12" cy="12" r="2.5" />
  </Base>
);

export const IconEyeOff = (props: IconProps) => (
  <Base {...props}>
    <path d="M4 4l16 16" />
    <path d="M9.9 5.2A9.9 9.9 0 0112 5c6.5 0 10 6 10 6a17 17 0 01-3.4 4M6.3 7.3A17 17 0 002 11s3.5 6 10 6a9.6 9.6 0 004-.85" />
  </Base>
);

export const IconWarning = (props: IconProps) => (
  <Base {...props}>
    <path d="M12 4l9 16H3z" />
    <path d="M12 10v4M12 17h.01" />
  </Base>
);

export const IconExternal = (props: IconProps) => (
  <Base {...props}>
    <path d="M14 4h6v6" />
    <path d="M20 4l-8 8" />
    <path d="M19 14v5a1 1 0 01-1 1H6a1 1 0 01-1-1V7a1 1 0 011-1h5" />
  </Base>
);
