/** Ortak metrik çizimi (ucli Metrikler + Metrikler sekmesi): satır içi SVG zaman serisi. Veri yalnız sayı olarak çizilir. */

export function fmtBytes(n: number): string {
  if (n >= 1 << 30) return (n / (1 << 30)).toFixed(1) + " GiB";
  if (n >= 1 << 20) return (n / (1 << 20)).toFixed(1) + " MiB";
  if (n >= 1 << 10) return (n / (1 << 10)).toFixed(0) + " KiB";
  return String(n) + " B";
}

export function Spark({ label, values, fmt }: { label: string; values: (number | null)[]; fmt: (v: number) => string }) {
  const pts = values.map((v, i) => ({ v, i })).filter((p): p is { v: number; i: number } => p.v != null);
  const W = 300, H = 48;
  const max = Math.max(1e-9, ...pts.map((p) => p.v));
  const n = Math.max(1, values.length - 1);
  const d = pts.map((p, k) => `${k ? "L" : "M"}${((p.i / n) * W).toFixed(1)},${(H - 2 - (p.v / max) * (H - 4)).toFixed(1)}`).join(" ");
  const last = pts.length ? pts[pts.length - 1].v : null;
  return (
    <div style={{ margin: "6px 0", maxWidth: 340 }}>
      <div style={{ fontSize: 12 }}>
        {label}: <strong>{last == null ? "-" : fmt(last)}</strong> <span className="opts-hint">(max {fmt(max)})</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label={label} preserveAspectRatio="none" style={{ background: "rgba(127,127,127,.12)", borderRadius: 4 }}>
        {d && <path d={d} fill="none" stroke="#2563eb" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />}
      </svg>
    </div>
  );
}
