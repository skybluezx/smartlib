import { useEffect, useState, type Dispatch, type SetStateAction } from 'react';

// Session-only: refresh/back restoration without leaking preferences to other tabs.
export function useSessionState<T>(key: string, initial: T): [T, Dispatch<SetStateAction<T>>] {
  const storageKey = `smartlib.analytics.session.v1.${key}`;
  const [value,setValue] = useState<T>(() => {
    try {
      const raw = sessionStorage.getItem(storageKey);
      if (!raw) return initial;
      const parsed: unknown = JSON.parse(raw);
      if (typeof parsed !== typeof initial || parsed === null || Array.isArray(parsed) !== Array.isArray(initial)) return initial;
      return parsed as T;
    } catch { return initial; }
  });
  useEffect(() => { try { sessionStorage.setItem(storageKey,JSON.stringify(value)); } catch { /* Storage can be unavailable. */ } }, [storageKey,value]);
  return [value,setValue];
}
