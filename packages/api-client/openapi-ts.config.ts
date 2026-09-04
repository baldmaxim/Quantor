import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: './openapi.json',
  output: {
    path: './src',
    postProcess: [],
  },
  plugins: [
    {
      name: '@hey-api/client-fetch',
      // Базовый адрес API подставляется на этапе исполнения — см. runtime.ts.
      runtimeConfigPath: './runtime.ts',
    },
  ],
});
