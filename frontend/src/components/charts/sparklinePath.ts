// ============================================================
// OPSYN CHARTS — sparkline geometry (pure, tested)
// ============================================================

/**
 * SVG path for a series, split into separate segments at nulls.
 * `minSpan` stops plain min–max scaling from inflating noise: a 97.1–97.8%
 * wobble must not look like a collapse. The vertical range is at least
 * `minSpan`, centred on the data.
 */
export function sparklinePath(values: (number | null)[], width: number, height: number, pad = 2, minSpan = 0): string {
  const nums = values.filter((v): v is number => v !== null);
  if (nums.length === 0) return '';
  let min = Math.min(...nums);
  let max = Math.max(...nums);
  if (max - min < minSpan) {
    const mid = (max + min) / 2;
    min = mid - minSpan / 2;
    max = mid + minSpan / 2;
  }
  const span = max - min || 1;
  const step = values.length > 1 ? (width - pad * 2) / (values.length - 1) : 0;
  const y = (v: number) => (max === min ? height / 2 : pad + (1 - (v - min) / span) * (height - pad * 2));

  let d = '';
  let pen = false;
  values.forEach((v, i) => {
    if (v === null) { pen = false; return; }
    d += `${pen ? 'L' : 'M'}${(pad + i * step).toFixed(1)} ${y(v).toFixed(1)} `;
    pen = true;
  });
  return d.trim();
}
