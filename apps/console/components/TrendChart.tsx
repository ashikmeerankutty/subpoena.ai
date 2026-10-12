"use client";

import { Box } from "@twilio-paste/core/box";
import { Text } from "@twilio-paste/core/text";
import { useMemo, useState } from "react";

// Verdicts are states, so they wear status colors (validated for color-vision deficiency in this
// stacking order: green and red never touch). Identity never rests on color alone: the legend,
// 2px gaps between segments and the hover tooltip all name them.
const SERIES: { key: string; label: string; color: string }[] = [
  { key: "APPROVE", label: "Approved", color: "#1a9e55" },
  { key: "HOLD", label: "Held", color: "#f29100" },
  { key: "BLOCK", label: "Blocked", color: "#cf2d4f" },
  { key: "PENDING", label: "In progress", color: "#a3abbc" },
];
const INK = "#121c2d", MUTED = "#606b85", GRID = "#e1e3ea";

type Bucket = { t: number; counts: Record<string, number>; total: number };

/** Every bucket in the window, including empty ones, so time reads at an even pace. */
function timeline(series: Record<string, any>[], hours: number, minutes: number): Bucket[] {
  const step = minutes * 60_000;
  const end = Math.floor(Date.now() / step) * step;
  const n = Math.max(1, Math.round((hours * 60) / minutes));
  const byT = new Map(series.map((s) => [Math.floor(new Date(s.hour).getTime() / step) * step, s]));
  return Array.from({ length: n }, (_, i) => {
    const t = end - (n - 1 - i) * step;
    const s = byT.get(t) ?? {};
    const counts = Object.fromEntries(SERIES.map(({ key }) => [key, Number(s[key] ?? 0)]));
    return { t, counts, total: SERIES.reduce((a, { key }) => a + counts[key], 0) };
  });
}

/** Four even steps of 1, 2 or 5 × 10^k, so every gridline lands on a round number. */
function niceStep(v: number): number {
  const raw = Math.max(1, v / 4);
  const mag = 10 ** Math.floor(Math.log10(raw));
  return ([1, 2, 5, 10].map((m) => m * mag).find((m) => m >= raw) ?? raw);
}

function label(t: number, hours: number) {
  const d = new Date(t);
  if (hours > 48) return d.toLocaleDateString([], { weekday: "short", day: "numeric" });
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function TrendChart({ series, hours, bucketMinutes = 60 }: { series: Record<string, any>[]; hours: number; bucketMinutes?: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const buckets = useMemo(() => timeline(series, hours, bucketMinutes), [series, hours, bucketMinutes]);
  const totals = Object.fromEntries(SERIES.map(({ key }) => [key, buckets.reduce((a, b) => a + b.counts[key], 0)]));
  const all = buckets.reduce((a, b) => a + b.total, 0);

  const W = 720, H = 220, L = 34, R = 8, T = 10, B = 26;
  const plotW = W - L - R, plotH = H - T - B;
  const step = niceStep(Math.max(...buckets.map((b) => b.total), 1));
  const max = step * 4;
  const ticks = [0, 1, 2, 3, 4].map((i) => i * step);
  const slot = plotW / buckets.length;
  const bw = Math.max(2, Math.min(26, slot * 0.68));
  const y = (v: number) => T + plotH - (v / max) * plotH;
  const every = Math.ceil(buckets.length / 7);
  const h = hover != null ? buckets[hover] : null;

  return (
    <Box>
      <Box display="flex" flexWrap="wrap" alignItems="baseline" columnGap="space70" rowGap="space30" marginBottom="space50">
        <Box>
          <Text as="div" fontSize="fontSize70" lineHeight="lineHeight70" fontWeight="fontWeightBold">{all.toLocaleString()}</Text>
          <Text as="div" fontSize="fontSize20" color="colorTextWeak">evaluations</Text>
        </Box>
        {SERIES.map(({ key, label: name, color }) => (
          <Box key={key} display="flex" alignItems="center" columnGap="space30">
            <span style={{ width: 10, height: 10, borderRadius: 3, background: color, display: "inline-block" }} />
            <Text as="span" fontSize="fontSize30" fontWeight="fontWeightSemibold">{totals[key].toLocaleString()}</Text>
            <Text as="span" fontSize="fontSize20" color="colorTextWeak">{name}</Text>
          </Box>
        ))}
      </Box>

      <Box position="relative">
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" style={{ display: "block", overflow: "visible" }}
          aria-label={`Evaluations by verdict: ${SERIES.map(({ key, label: n }) => `${totals[key]} ${n.toLowerCase()}`).join(", ")}`}
          onMouseLeave={() => setHover(null)}
          // Keyboard: focus the chart, then Left/Right walk the bars and show the same tooltip.
          tabIndex={0} className="chart-bar"
          onFocus={() => setHover((v) => v ?? Math.max(0, buckets.findLastIndex((b) => b.total > 0)))}
          onBlur={() => setHover(null)}
          onKeyDown={(e) => {
            const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
            if (!d) return;
            e.preventDefault();
            setHover((v) => Math.min(buckets.length - 1, Math.max(0, (v ?? 0) + d)));
          }}>
          {ticks.map((v) => (
            <g key={v}>
              <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke={GRID} strokeWidth={1} strokeDasharray={v === 0 ? undefined : "2 4"} />
              <text x={L - 8} y={y(v) + 4} fontSize="11" fill={MUTED} textAnchor="end" style={{ fontVariantNumeric: "tabular-nums" }}>{v}</text>
            </g>
          ))}
          {buckets.map((b, i) => i % every === 0 ? (
            <text key={b.t} x={L + slot * i + slot / 2} y={H - 6} fontSize="11" fill={MUTED} textAnchor="middle">{label(b.t, hours)}</text>
          ) : null)}
          {buckets.map((b, i) => {
            const cx = L + slot * i + slot / 2;
            const x = cx - bw / 2;
            const segs = SERIES.filter(({ key }) => b.counts[key] > 0);
            let acc = 0;
            return (
              <g key={b.t} opacity={hover == null || hover === i ? 1 : 0.45}>
                {hover === i ? <rect x={L + slot * i} y={T} width={slot} height={plotH} fill="#f4f4f6" rx={4} /> : null}
                {segs.map(({ key, color }, j) => {
                  const y0 = y(acc), y1 = y(acc + b.counts[key]);
                  acc += b.counts[key];
                  const top = j === segs.length - 1;
                  // 2px surface gap between stacked segments; only the top end is rounded.
                  const h = Math.max(1, y0 - y1 - (j > 0 ? 2 : 0));
                  const r = top ? Math.min(4, h, bw / 2) : 0;
                  const yy = y0 - (j > 0 ? 2 : 0) - h;
                  return <path key={key} fill={color}
                    d={`M${x},${yy + h} V${yy + r} Q${x},${yy} ${x + r},${yy} H${x + bw - r} Q${x + bw},${yy} ${x + bw},${yy + r} V${yy + h} Z`} />;
                })}
                {/* Hit target: the whole column, much larger than the bar. */}
                <rect x={L + slot * i} y={T} width={slot} height={plotH} fill="transparent" onMouseEnter={() => setHover(i)} />
              </g>
            );
          })}
        </svg>

        {h && hover != null ? (
          <div role="tooltip" aria-live="polite" style={{
            position: "absolute", top: 0, pointerEvents: "none", minWidth: 150,
            left: `${((L + slot * hover + slot / 2) / W) * 100}%`,
            transform: `translateX(${hover > buckets.length / 2 ? "calc(-100% - 12px)" : "12px"})`,
            background: "#fff", border: `1px solid ${GRID}`, borderRadius: 8, padding: "8px 10px",
            boxShadow: "0 6px 16px rgba(18, 28, 45, 0.12)", fontSize: 12, color: INK,
          }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>
              {new Date(h.t).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })}
              <span style={{ color: MUTED, fontWeight: 400 }}> · {h.total} total</span>
            </div>
            {[...SERIES].reverse().map(({ key, label: name, color }) => (
              <div key={key} style={{ display: "flex", alignItems: "center", gap: 6, color: h.counts[key] ? INK : MUTED }}>
                <span style={{ width: 8, height: 8, borderRadius: 2, background: color }} />
                <span style={{ flex: 1 }}>{name}</span>
                <span style={{ fontVariantNumeric: "tabular-nums", fontWeight: 600 }}>{h.counts[key]}</span>
              </div>
            ))}
          </div>
        ) : null}
      </Box>
      <table className="sr-only">
        <caption>Evaluations by verdict, per {bucketMinutes >= 60 ? `${bucketMinutes / 60} hour` : `${bucketMinutes} minutes`}</caption>
        <thead><tr><th scope="col">Time</th>{SERIES.map(({ key, label: n }) => <th key={key} scope="col">{n}</th>)}</tr></thead>
        <tbody>
          {buckets.filter((b) => b.total > 0).map((b) => (
            <tr key={b.t}>
              <th scope="row">{new Date(b.t).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })}</th>
              {SERIES.map(({ key }) => <td key={key}>{b.counts[key]}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {all === 0 ? <Text as="p" color="colorTextWeak" marginTop="space30">No evaluations in this window yet.</Text> : null}
    </Box>
  );
}
