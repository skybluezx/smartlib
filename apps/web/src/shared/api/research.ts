import { runtimeConfig } from '../config/runtime';
const base = runtimeConfig.apiBaseUrl.replace(/\/$/, '') + '/api/v1/research';
export async function api<T>(path: string, body?: unknown, file?: File): Promise<T> {
  const form = file ? new FormData() : undefined; if (file) form?.append('file', file);
  const r = await fetch(base + path, { method: body !== undefined || file ? 'POST' : 'GET', credentials: 'same-origin',
    ...(body !== undefined ? { headers: { 'Content-Type': 'application/json' } } : {}), ...(form ? { body: form } : body !== undefined ? { body: JSON.stringify(body) } : {}) });
  const data = await r.json() as T & { detail?: unknown };
  if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? '请求失败'));
  return data;
}
interface Direction { code: string; name: string; version?: string; count: number; papers: string[] }
export interface Analysis { papers: number; classified?: number; directions: Direction[]; trends: (Direction & { year: number | null })[];
  intersections: { a: string; b: string; count: number; papers: string[] }[];
  collaboration: { a: string; b: string; a_name: string; b_name: string; shared: { name: string }[]; a_papers: string[]; b_papers: string[]; note: string }[];
  paper_titles?: Record<string, string>; note?: string }
