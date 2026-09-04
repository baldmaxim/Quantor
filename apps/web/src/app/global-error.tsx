'use client';

/**
 * Последний рубеж: ошибка в корневом макете.
 *
 * Здесь нельзя опираться ни на токены, ни на компоненты — сломаться могло что угодно
 * выше по дереву. Поэтому разметка минимальная и со своими цветами.
 */
const GlobalError = ({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) => (
  <html lang="ru">
    <body
      style={{
        margin: 0,
        minHeight: '100dvh',
        display: 'grid',
        placeItems: 'center',
        fontFamily: 'system-ui, sans-serif',
        background: '#f1f4f7',
        color: '#0f141a',
      }}
    >
      <div style={{ maxWidth: '48ch', padding: 24, textAlign: 'center' }}>
        <h1 style={{ fontSize: 18, margin: '0 0 8px' }}>Портал не запустился</h1>
        <p style={{ fontSize: 14, color: '#55606e', margin: '0 0 16px' }}>
          Произошла ошибка на самом верхнем уровне. Перезагрузите страницу.
          {error.digest && <> Код: {error.digest}.</>}
        </p>
        <button
          type="button"
          onClick={reset}
          style={{
            height: 32,
            padding: '0 16px',
            borderRadius: 4,
            border: '1px solid #1a5fa8',
            background: '#1a5fa8',
            color: '#ffffff',
            fontSize: 13,
            cursor: 'pointer',
          }}
        >
          Перезагрузить
        </button>
      </div>
    </body>
  </html>
);

export default GlobalError;
