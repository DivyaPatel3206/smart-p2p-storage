// Small reusable UI pieces: icons, stat card, donut chart, bar chart.
// Charts are hand-written SVG so the project needs no chart library.

const paths = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  upload: "M12 16V4m0 0-5 5m5-5 5 5M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3",
  files: "M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zm7 0v5h5",
  network: "M12 5a2 2 0 1 0 0-.01M5 19a2 2 0 1 0 0-.01M19 19a2 2 0 1 0 0-.01M12 7v4m0 0-6 6m6-6 6 6",
  chart: "M4 20V10m6 10V4m6 16v-7m4 7H2",
  chunk: "M4 4h7v7H4zm9 0h7v7h-7zM4 13h7v7H4zm9 0h7v7h-7z",
  copy: "M8 8h11v11H8zM5 16V5h11",
  peers: "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zm-6 9a6 6 0 0 1 12 0m2-9a3 3 0 1 0 0-6m2 15a5 5 0 0 0-3-4.6",
  shield: "M12 3 4 6v6c0 4.5 3.4 8 8 9 4.6-1 8-4.5 8-9V6z",
  spark: "M12 3v4m0 10v4M3 12h4m10 0h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zm9 3-4.3-4.3",
  download: "M12 4v12m0 0-5-5m5 5 5-5M4 20h16",
  image: "M4 5h16v14H4zm0 11 5-5 4 4 3-3 4 4M9 9.5a1.5 1.5 0 1 0 0-.01",
};

export function Icon({ name, size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={paths[name] || paths.spark} />
    </svg>
  );
}

export function Stat({ icon, tone = "", label, value, foot }) {
  return (
    <div className="card stat">
      <div className="label"><span className={`ico ${tone}`}><Icon name={icon} size={16} /></span>{label}</div>
      <div className="value">{value}</div>
      {foot && <div className="foot">{foot}</div>}
    </div>
  );
}

// Donut chart: segments = [{value, color, label}]
export function Donut({ segments, size = 168, stroke = 18, center, caption }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  let offset = 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={caption}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#eef2f8" strokeWidth={stroke} />
      {segments.map((s, i) => {
        const len = (s.value / total) * c;
        const el = (
          <circle key={i} cx={size / 2} cy={size / 2} r={r} fill="none" stroke={s.color}
            strokeWidth={stroke} strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-offset}
            strokeLinecap={len > 4 ? "round" : "butt"} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
        );
        offset += len;
        return el;
      })}
      <text x="50%" y="48%" textAnchor="middle" fontSize="28" fontWeight="700" fill="#0f1b33">{center}</text>
      <text x="50%" y="62%" textAnchor="middle" fontSize="11" fill="#8a96ab">{caption}</text>
    </svg>
  );
}

// Vertical bars (used for block-stat latency, like the "Learning Time" bars in the reference)
export function Bars({ values, height = 120, color = "#f5a524", labelFn }) {
  if (!values.length) return <div className="empty">no samples yet</div>;
  const max = Math.max(...values) || 1;
  const w = 100 / values.length;
  return (
    <svg width="100%" height={height} viewBox={`0 0 100 ${height}`} preserveAspectRatio="none">
      {values.map((v, i) => {
        const h = Math.max(2, (v / max) * (height - 6));
        return (
          <rect key={i} x={i * w + w * 0.18} y={height - h} width={w * 0.64} height={h} rx="0.8"
            fill={color} opacity={0.45 + 0.55 * (v / max)}>
            <title>{labelFn ? labelFn(v, i) : v}</title>
          </rect>
        );
      })}
    </svg>
  );
}

export function Meter({ value, tone = "" }) {
  const pct = Math.max(0, Math.min(1, value || 0)) * 100;
  return <div className={`bar ${tone}`}><span style={{ width: `${pct}%` }} /></div>;
}

export function DupBadge({ kind }) {
  if (kind === "file") return <span className="badge red">file duplicate</span>;
  if (kind === "chunks") return <span className="badge amber">partial (chunks)</span>;
  if (kind === "near") return <span className="badge blue">near-duplicate</span>;
  return <span className="badge green">new content</span>;
}
