import { PlatformLivePanel } from '../features/platform/PlatformLivePanel';
import { GraphLivePanel } from '../features/platform/GraphLivePanel';
import { SearchLivePanel } from '../features/platform/SearchLivePanel';
import { UnavailableRoute } from './UnavailableRoute';

export function InfrastructureRoute() {
  return <><PlatformLivePanel /><SearchLivePanel /><GraphLivePanel /><UnavailableRoute /></>;
}
