"use client";

import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, LabelList, Pie, PieChart,
  ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import type { ChartSpec } from "@/lib/analyst";

export const PALETTE = [
  "var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)",
  "oklch(0.6 0.08 140)", "oklch(0.62 0.09 320)", "oklch(0.68 0.07 50)", "oklch(0.55 0.1 240)", "oklch(0.7 0.06 180)",
];

const compact = new Intl.NumberFormat("en-GB", { notation: "compact", maximumFractionDigits: 1 });
const full = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 });
export const fmt = (v: unknown) => (typeof v === "number" ? full.format(v) : v === null || v === undefined ? "NULL" : String(v));
const tick = (v: unknown) => (typeof v === "number" ? compact.format(v) : String(v).length > 14 ? `${String(v).slice(0, 13)}…` : String(v));

const AXIS = { stroke: "var(--muted-foreground)", fontSize: 11 } as const;
const GRID = "var(--border)";

function TooltipBox({ active, payload, label }: { active?: boolean; payload?: { name?: string; value?: unknown; color?: string; payload?: Record<string, unknown> }[]; label?: unknown }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-sm">
      {label !== undefined && label !== "" && <p className="mb-1 font-medium">{String(label)}</p>}
      {payload.map((p, i) => (
        <p key={i} className="flex items-center gap-2 tabular-nums">
          <span className="inline-block size-2 rounded-sm" style={{ background: p.color }} />
          <span className="text-muted-foreground">{p.name}</span>
          <span className="ml-auto pl-3 font-medium">{fmt(p.value)}</span>
        </p>
      ))}
    </div>
  );
}

const tooltip = <Tooltip content={<TooltipBox />} cursor={{ fill: "var(--accent)", opacity: 0.5 }} />;

function xAxisProps(spec: ChartSpec, n: number) {
  const angled = n > 8;
  return {
    dataKey: "x", ...AXIS, padding: { left: 8, right: 22 }, tickFormatter: tick, interval: n > 24 ? ("preserveStartEnd" as const) : 0,
    angle: angled ? -35 : 0, textAnchor: angled ? ("end" as const) : ("middle" as const), height: angled ? 64 : 36,
    label: spec.x_label ? { value: spec.x_label, position: "insideBottom" as const, offset: angled ? -2 : -6, fill: "var(--muted-foreground)", fontSize: 11 } : undefined,
  };
}
const yLabel = (spec: ChartSpec) => (spec.y_label ? { value: spec.y_label, angle: -90, position: "insideLeft" as const, fill: "var(--muted-foreground)", fontSize: 11, dy: 30 } : undefined);

function Cartesian({ spec }: { spec: ChartSpec }) {
  const n = spec.data.length;
  const multi = spec.y_keys.length > 1;
  const common = { data: spec.data, margin: { top: 12, right: 16, bottom: 8, left: 8 } };
  const legend = multi ? <Legend wrapperStyle={{ fontSize: 12 }} verticalAlign="top" height={28} /> : null;
  if (spec.type === "hbar") {
    const width = Math.min(180, 24 + Math.max(...spec.data.map((d) => String(d.x).length)) * 6.2);
    return (
      <BarChart {...common} layout="vertical" margin={{ top: 8, right: 56, bottom: 8, left: 8 }}>
        <CartesianGrid stroke={GRID} horizontal={false} />
        <XAxis type="number" {...AXIS} tickFormatter={tick} />
        <YAxis type="category" dataKey="x" width={width} {...AXIS} tickFormatter={(v) => String(v)} interval={0} />
        {tooltip}
        {legend}
        {spec.y_keys.map((k, i) => (
          <Bar key={k} dataKey={k} fill={PALETTE[i % PALETTE.length]} radius={[0, 3, 3, 0]}>
            {n <= 15 && <LabelList dataKey={k} position="right" formatter={(v: unknown) => tick(v)} style={{ fill: "var(--foreground)", fontSize: 11 }} />}
          </Bar>
        ))}
      </BarChart>
    );
  }
  if (spec.type === "bar" || spec.type === "histogram") {
    return (
      <BarChart {...common} barGap={spec.type === "histogram" ? 0 : 4} barCategoryGap={spec.type === "histogram" ? 1 : "20%"}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis {...xAxisProps(spec, n)} dataKey={spec.type === "histogram" ? "label" : "x"} />
        <YAxis {...AXIS} tickFormatter={tick} label={yLabel(spec)} width={56} />
        {tooltip}
        {legend}
        {spec.y_keys.map((k, i) => (
          <Bar key={k} dataKey={k} fill={PALETTE[i % PALETTE.length]} radius={spec.type === "histogram" ? 0 : [3, 3, 0, 0]}>
            {n <= 12 && !multi && <LabelList dataKey={k} position="top" formatter={(v: unknown) => tick(v)} style={{ fill: "var(--foreground)", fontSize: 11 }} />}
          </Bar>
        ))}
      </BarChart>
    );
  }
  if (spec.type === "area") {
    return (
      <AreaChart {...common}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis {...xAxisProps(spec, n)} />
        <YAxis {...AXIS} tickFormatter={tick} label={yLabel(spec)} width={56} />
        {tooltip}
        {legend}
        {spec.y_keys.map((k, i) => (
          <Area key={k} type="monotone" dataKey={k} stroke={PALETTE[i % PALETTE.length]} fill={PALETTE[i % PALETTE.length]} fillOpacity={0.18} strokeWidth={2} />
        ))}
      </AreaChart>
    );
  }
  return (
    <LineChart {...common}>
      <CartesianGrid stroke={GRID} vertical={false} />
      <XAxis {...xAxisProps(spec, n)} />
      <YAxis {...AXIS} tickFormatter={tick} label={yLabel(spec)} width={56} />
      {tooltip}
      {legend}
      {spec.y_keys.map((k, i) => (
        <Line key={k} type="monotone" dataKey={k} stroke={PALETTE[i % PALETTE.length]} strokeWidth={2} dot={n <= 36 ? { r: 3 } : false} activeDot={{ r: 5 }} connectNulls />
      ))}
    </LineChart>
  );
}

function PieBody({ spec }: { spec: ChartSpec }) {
  const total = spec.data.reduce((s, d) => s + (Number(d.value) || 0), 0);
  return (
    <PieChart>
      <Pie data={spec.data} dataKey="value" nameKey="name" innerRadius={spec.type === "donut" ? "55%" : 0} outerRadius="80%" paddingAngle={spec.type === "donut" ? 2 : 0} stroke="var(--card)" label={({ percent }: { percent?: number }) => `${((percent ?? 0) * 100).toFixed(1)}%`} labelLine={false}>
        {spec.data.map((_, i) => (
          <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
        ))}
      </Pie>
      <Tooltip content={({ active, payload }) => active && payload?.length ? (
        <div className="rounded-md border bg-popover px-3 py-2 text-xs shadow-sm">
          <p className="font-medium">{String(payload[0].name)}</p>
          <p className="tabular-nums">{fmt(payload[0].value)} ({total ? (((Number(payload[0].value) || 0) / total) * 100).toFixed(1) : 0}%)</p>
        </div>
      ) : null} />
      <Legend wrapperStyle={{ fontSize: 12 }} />
    </PieChart>
  );
}

function ScatterBody({ spec }: { spec: ChartSpec }) {
  const groups = spec.series_values?.length ? spec.series_values : [null];
  return (
    <ScatterChart margin={{ top: 12, right: 16, bottom: 12, left: 8 }}>
      <CartesianGrid stroke={GRID} />
      <XAxis type="number" dataKey="x" name={spec.x_label || "x"} {...AXIS} tickFormatter={tick} label={spec.x_label ? { value: spec.x_label, position: "insideBottom", offset: -6, fill: "var(--muted-foreground)", fontSize: 11 } : undefined} domain={["auto", "auto"]} />
      <YAxis type="number" dataKey="y" name={spec.y_label || "y"} {...AXIS} tickFormatter={tick} label={yLabel(spec)} width={56} domain={["auto", "auto"]} />
      <ZAxis range={[36, 36]} />
      <Tooltip content={<TooltipBox />} cursor={{ strokeDasharray: "3 3" }} />
      {groups.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
      {groups.map((g, i) => (
        <Scatter key={g ?? "all"} name={g ?? (spec.y_label || "points")} data={g === null ? spec.data : spec.data.filter((d) => d.series === g)} fill={PALETTE[i % PALETTE.length]} fillOpacity={0.6} />
      ))}
    </ScatterChart>
  );
}

/** Box plot drawn directly in SVG so that it exports like every other chart. */
function BoxBody({ spec }: { spec: ChartSpec }) {
  const rows = spec.data as unknown as { group: string; min: number; q1: number; median: number; q3: number; max: number; n: number; outliers: number[] }[];
  const all = rows.flatMap((r) => [r.min, r.max, ...r.outliers]);
  const lo = Math.min(...all), hi = Math.max(...all);
  const W = 640, H = 300, L = 60, R = 16, T = 12, B = 56;
  const pad = (hi - lo || 1) * 0.06;
  const y = (v: number) => T + (H - T - B) * (1 - (v - (lo - pad)) / (hi - lo + 2 * pad));
  const slot = (W - L - R) / rows.length, bw = Math.min(56, slot * 0.5);
  const ticks = Array.from({ length: 5 }, (_, i) => lo + ((hi - lo) * i) / 4);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" role="img" aria-label={spec.title} style={{ fontSize: 11 }}>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke={GRID} />
          <text x={L - 6} y={y(t) + 4} textAnchor="end" fill="var(--muted-foreground)">{tick(t)}</text>
        </g>
      ))}
      {rows.map((r, i) => {
        const cx = L + slot * (i + 0.5);
        const color = PALETTE[i % PALETTE.length];
        return (
          <g key={r.group}>
            <title>{`${r.group}: median ${fmt(r.median)}, IQR ${fmt(r.q1)} to ${fmt(r.q3)}, n=${r.n}`}</title>
            <line x1={cx} x2={cx} y1={y(r.min)} y2={y(r.q1)} stroke={color} strokeWidth={1.5} />
            <line x1={cx} x2={cx} y1={y(r.q3)} y2={y(r.max)} stroke={color} strokeWidth={1.5} />
            <line x1={cx - bw / 4} x2={cx + bw / 4} y1={y(r.min)} y2={y(r.min)} stroke={color} strokeWidth={1.5} />
            <line x1={cx - bw / 4} x2={cx + bw / 4} y1={y(r.max)} y2={y(r.max)} stroke={color} strokeWidth={1.5} />
            <rect x={cx - bw / 2} width={bw} y={y(r.q3)} height={Math.max(1, y(r.q1) - y(r.q3))} fill={color} fillOpacity={0.25} stroke={color} strokeWidth={1.5} rx={2} />
            <line x1={cx - bw / 2} x2={cx + bw / 2} y1={y(r.median)} y2={y(r.median)} stroke="var(--foreground)" strokeWidth={2} />
            {r.outliers.map((o, j) => <circle key={j} cx={cx} cy={y(o)} r={2.5} fill="none" stroke={color} />)}
            <text x={cx} y={H - B + 18} textAnchor="middle" fill="var(--foreground)">{r.group.length > 14 ? `${r.group.slice(0, 13)}…` : r.group}</text>
            <text x={cx} y={H - B + 32} textAnchor="middle" fill="var(--muted-foreground)">n={r.n}</text>
          </g>
        );
      })}
      {spec.y_label && <text x={14} y={H / 2 - 10} transform={`rotate(-90 14 ${H / 2 - 10})`} textAnchor="middle" fill="var(--muted-foreground)">{spec.y_label}</text>}
    </svg>
  );
}

function cellColor(v: number | null, correlation: boolean, max: number): string {
  if (v === null) return "transparent";
  if (correlation) {
    const a = Math.min(1, Math.abs(v));
    return `color-mix(in oklch, ${v >= 0 ? "var(--chart-1)" : "var(--chart-4)"} ${Math.round(a * 85)}%, transparent)`;
  }
  return `color-mix(in oklch, var(--chart-1) ${Math.round((v / (max || 1)) * 85)}%, transparent)`;
}

function HeatBody({ spec }: { spec: ChartSpec }) {
  const xs = spec.x_values ?? [], ys = spec.y_values ?? [];
  const corr = spec.type === "correlation";
  const cell = new Map(spec.data.map((d) => [`${d.x}|${d.y}`, d.value as number | null]));
  const max = Math.max(...spec.data.map((d) => Number(d.value) || 0), 0);
  const cw = Math.max(40, Math.min(84, 620 / Math.max(xs.length, 1)));
  const ch = 32, L = 130;
  const rotate = xs.some((x) => x.length > 5);
  const T = rotate ? 62 : 34;
  const W = L + cw * xs.length + 8, H = T + ch * ys.length + 8;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={spec.title} style={{ fontSize: 11, maxHeight: 420 }}>
      {xs.map((x, i) => (
        <text key={x} x={L + cw * i + cw / 2} y={T - 8} transform={rotate ? `rotate(-30 ${L + cw * i + cw / 2} ${T - 8})` : undefined} textAnchor={rotate ? "start" : "middle"} fill="var(--muted-foreground)">{x.length > 14 ? `${x.slice(0, 13)}…` : x}</text>
      ))}
      {ys.map((y, j) => (
        <g key={y}>
          <text x={L - 8} y={T + ch * j + ch / 2 + 4} textAnchor="end" fill="var(--muted-foreground)">{y.length > 18 ? `${y.slice(0, 17)}…` : y}</text>
          {xs.map((x, i) => {
            const v = cell.get(`${x}|${y}`) ?? null;
            return (
              <g key={x}>
                <title>{`${x} / ${y}: ${v === null ? "n/a" : fmt(v)}`}</title>
                <rect x={L + cw * i + 1} y={T + ch * j + 1} width={cw - 2} height={ch - 2} rx={3} fill={cellColor(v, corr, max)} stroke="var(--border)" />
                <text x={L + cw * i + cw / 2} y={T + ch * j + ch / 2 + 4} textAnchor="middle" fill="var(--foreground)">{v === null ? "" : corr ? v.toFixed(2) : tick(v)}</text>
              </g>
            );
          })}
        </g>
      ))}
    </svg>
  );
}

export function ChartBody({ spec }: { spec: ChartSpec }) {
  const tall = spec.type === "heatmap" || spec.type === "correlation";
  if (spec.data.length === 0) return <p className="p-6 text-sm text-muted-foreground">There is no data to plot.</p>;
  if (tall) return <HeatBody spec={spec} />;
  if (spec.type === "box") return <div className="h-[320px]"><BoxBody spec={spec} /></div>;
  return (
    <div className="h-[320px]">
      <ResponsiveContainer width="100%" height="100%">
        {spec.type === "pie" || spec.type === "donut" ? <PieBody spec={spec} /> : spec.type === "scatter" ? <ScatterBody spec={spec} /> : <Cartesian spec={spec} />}
      </ResponsiveContainer>
    </div>
  );
}
