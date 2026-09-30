import { GovernanceDashboard } from '../features/governance/GovernanceDashboard';
import { DemoBoundary } from './DemoBoundary';

export function GovernanceRoute() {
  return <DemoBoundary><GovernanceDashboard /></DemoBoundary>;
}
