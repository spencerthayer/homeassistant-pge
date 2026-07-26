/** Tiny hand-rolled SVG helpers for sparklines. */

export function sparklineSvg(values, { width = 72, height = 28, stroke = "var(--pge-series-kwh)" } = {}) {
  const nums = (values || []).filter((v) => v != null && Number.isFinite(Number(v))).map(Number);
  if (nums.length < 2) {
    return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" aria-hidden="true"></svg>`;
  }
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const span = max - min || 1;
  const step = width / (nums.length - 1);
  const pts = nums
    .map((v, i) => {
      const x = i * step;
      const y = height - 2 - ((v - min) / span) * (height - 4);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" aria-hidden="true">
    <polyline fill="none" stroke="${stroke}" stroke-width="1.5" points="${pts}" />
  </svg>`;
}
