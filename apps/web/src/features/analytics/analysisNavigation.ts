export const analysisTabs = ['journals','funding','disciplines','people_collaboration','institution_collaboration'] as const;
export const analysisSections = ['basic','topics','records'] as const;
export function analysisPosition(params: URLSearchParams) {
  return { tab: Math.max(0, analysisTabs.findIndex(t => t === params.get('tab'))),
    section: Math.max(0, analysisSections.findIndex(t => t === params.get('section'))) };
}
