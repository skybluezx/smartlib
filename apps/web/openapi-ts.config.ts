import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: '../../packages/api-contracts/openapi/smartlib-platform-v1.json',
  output: {
    path: 'src/generated/smartlib-api',
    clean: true,
  },
});
