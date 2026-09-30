export function historyDiff(before: Record<string, unknown>, after: Record<string, unknown>) {
  return [...new Set([...Object.keys(before), ...Object.keys(after)])].sort()
    .filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
    .map((key) => ({ field: key, before: before[key], after: after[key] }));
}
