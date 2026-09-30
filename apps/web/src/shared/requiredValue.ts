/** Fail explicitly when an established internal invariant no longer holds. */
export function requiredValue<T>(value: T | null | undefined): T {
  if (value === null || value === undefined) throw new Error('预期的数据不存在，请刷新后重试。');
  return value;
}
