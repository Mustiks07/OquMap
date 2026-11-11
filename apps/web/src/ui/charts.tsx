/** Small accessible SVG charts: labelled axes, denominators in labels, colour + pattern/text never colour alone. */
import { useI18n } from "../i18n/I18n";
import { pct } from "./format";

export interface GroupedBar {
  label: string;
  values: { series: string; value: number | null; n?: number; note?: string }[];
}

const COLORS = ["var(--chart-a)", "var(--chart-b)", "var(--chart-c)", "var(--chart-neutral)"];

/** Horizontal grouped bars on a 0–100% axis. */
export function GroupedBars({ data, series, title, height }: { data: GroupedBar[]; series: string[]; title: string; height?: number }) {
  const { lang } = useI18n();
  const rowH = 26 * series.length + 18;
  const left = 170;
  const width = 640;
  const plotW = width - left - 70;
  const h = height ?? data.length * rowH + 40;
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${width} ${h}`} width="100%" role="img" aria-label={title} style={{ maxWidth: width }}>
        <title>{title}</title>
        {[0, 0.25, 0.5, 0.75, 1].map((x) => (
          <g key={x}>
            <line x1={left + x * plotW} x2={left + x * plotW} y1={8} y2={h - 26} stroke="var(--chart-grid)" />
            <text x={left + x * plotW} y={h - 10} fontSize="11" textAnchor="middle" fill="var(--color-text-muted)">
              {pct(x, lang, 0)}
            </text>
          </g>
        ))}
        {data.map((g, gi) => {
          const y0 = 10 + gi * rowH;
          return (
            <g key={g.label}>
              <text x={left - 8} y={y0 + rowH / 2} fontSize="12" textAnchor="end" dominantBaseline="middle" fill="var(--color-text)">
                {g.label}
              </text>
              {g.values.map((v, si) => {
                const y = y0 + si * 26;
                const w = v.value === null ? 0 : Math.max(0, Math.min(1, v.value)) * plotW;
                return (
                  <g key={v.series}>
                    <rect x={left} y={y} width={w} height={20} fill={COLORS[series.indexOf(v.series) % COLORS.length]} rx={3}
                      opacity={si === 0 ? 0.55 : 1} />
                    <text x={left + w + 6} y={y + 14} fontSize="12" fill="var(--color-text)">
                      {v.value === null ? "—" : pct(v.value, lang)} {v.n !== undefined ? `(n=${v.n})` : ""} {v.note ?? ""}
                    </text>
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
      <figcaption className="legend">
        {series.map((s, i) => (
          <span key={s}>
            <span className="legend-swatch" style={{ background: COLORS[i % COLORS.length], opacity: i === 0 ? 0.55 : 1 }} />
            {s}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

/** Before/after hours per topic. */
export function HoursChart({ rows, title, labels }: { rows: { code: string; before: number; after: number }[]; title: string; labels: [string, string] }) {
  const max = Math.max(1, ...rows.flatMap((r) => [r.before, r.after]));
  const width = 640;
  const left = 70;
  const plotW = width - left - 60;
  const rowH = 38;
  const h = rows.length * rowH + 30;
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${width} ${h}`} width="100%" role="img" aria-label={title} style={{ maxWidth: width }}>
        <title>{title}</title>
        {rows.map((r, i) => {
          const y = 6 + i * rowH;
          return (
            <g key={r.code}>
              <text x={left - 8} y={y + 16} fontSize="12" textAnchor="end" fill="var(--color-text)">{r.code}</text>
              <rect x={left} y={y} width={(r.before / max) * plotW} height={14} fill="var(--chart-neutral)" rx={2} />
              <text x={left + (r.before / max) * plotW + 4} y={y + 11} fontSize="11" fill="var(--color-text-muted)">{r.before}</text>
              <rect x={left} y={y + 16} width={(r.after / max) * plotW} height={14} fill="var(--chart-a)" rx={2} />
              <text x={left + (r.after / max) * plotW + 4} y={y + 27} fontSize="11" fill="var(--color-text)">
                {r.after} {r.after !== r.before ? `(${r.after > r.before ? "+" : "−"}${Math.abs(r.after - r.before)})` : ""}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="legend">
        <span><span className="legend-swatch" style={{ background: "var(--chart-neutral)" }} />{labels[0]}</span>
        <span><span className="legend-swatch" style={{ background: "var(--chart-a)" }} />{labels[1]}</span>
      </figcaption>
    </figure>
  );
}

export function heatColor(v: number | null | undefined): string {
  if (v === null || v === undefined) return "var(--color-surface-muted)";
  if (v < 0.45) return "var(--heat-0)";
  if (v < 0.55) return "var(--heat-1)";
  if (v < 0.65) return "var(--heat-2)";
  if (v < 0.75) return "var(--heat-3)";
  return "var(--heat-4)";
}
