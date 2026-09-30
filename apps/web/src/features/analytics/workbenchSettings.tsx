import { useSessionState } from './useSessionState';
import { createContext, useContext, useState, type ReactNode, type SetStateAction, type Dispatch } from 'react';

interface SettingsStore {
  values: Record<string, unknown>;
  replace: Dispatch<SetStateAction<Record<string, unknown>>>;
}
const SettingsContext = createContext<SettingsStore | null>(null);
export function WorkbenchSettingsProvider({ children }: { children: ReactNode }) {
  const [values, replace] = useSessionState<Record<string, unknown>>('preferences',{});
  return <SettingsContext.Provider value={{ values, replace }}>{children}</SettingsContext.Provider>;
}
export function useWorkbenchSettings(): SettingsStore {
  const store = useContext(SettingsContext);
  const [values, replace] = useState<Record<string, unknown>>({});
  return store ?? { values, replace };
}
export function useWorkbenchPreference<T>(key: string, initial: T): [T, Dispatch<SetStateAction<T>>] {
  const { values, replace } = useWorkbenchSettings();
  const value = Object.hasOwn(values, key) ? values[key] as T : initial;
  const setValue: Dispatch<SetStateAction<T>> = next => replace(previous => {
    const current = Object.hasOwn(previous, key) ? previous[key] as T : initial;
    return { ...previous, [key]: typeof next === 'function' ? (next as (value: T) => T)(current) : next };
  });
  return [value, setValue];
}
