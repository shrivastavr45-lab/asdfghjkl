export async function fetchAnalysis({ date, cutoffTime, refresh = false, signal }) {
  const params = new URLSearchParams({ date, cutoff_time: cutoffTime });
  if (refresh) params.set('refresh', 'true');
  const response = await fetch(`/api/analysis?${params.toString()}`, {
    headers: { Accept: 'application/json' },
    signal,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload.detail === 'string'
      ? payload.detail
      : `The API returned HTTP ${response.status}.`;
    throw new Error(detail);
  }
  return payload;
}
