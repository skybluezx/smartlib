/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SMARTLIB_API_BASE_URL?: string;
  readonly VITE_SMARTLIB_DEMO_MODE?: 'true' | 'false';
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
