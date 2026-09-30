import { useOutletContext } from 'react-router-dom';
import type { RoleId, RouteId } from '../shared/navigation/routes';

export interface AppOutletContext {
  role: RoleId;
  notify: (message: string) => void;
  navigateTo: (route: RouteId) => void;
}

export function useAppOutlet(): AppOutletContext {
  const context = useOutletContext<AppOutletContext | null>();
  return context ?? { role: '学校领导', notify: () => undefined, navigateTo: () => undefined };
}
