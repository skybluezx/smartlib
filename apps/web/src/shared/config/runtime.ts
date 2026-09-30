export const runtimeConfig = {
  demoMode: import.meta.env.VITE_SMARTLIB_DEMO_MODE !== 'false',
  apiBaseUrl: import.meta.env.VITE_SMARTLIB_API_BASE_URL ?? '',
} as const;
