"use client";

import { Box } from "@twilio-paste/core/box";
import { Text } from "@twilio-paste/core/text";

const SERIES: [string, string][] = [
  ["APPROVE", "#14b053"],
  ["BLOCK", "#d61f1f"],
  ["HOLD", "#f47c22"],
  ["PENDING", "#8891aa"],
];

export function TrendChart({ series }: { series: Record<string, any>[] }) {
  if (!series.length) {
    return <Text as="p" color="colorTextWeak">No evaluations in this window yet.</Text>;
  }
  const totals = series.map((s) => SERIES.reduce((a, [k]) => a + (s[k] ?? 0), 0));
  const max = Math.max(...totals, 1);
  const w = 640;
  const h = 160;
  const bw = Math.max(4, Math.min(28, w / series.length - 4));
  return (
    <Box>
      <svg viewBox={`0 0 ${w} ${h + 22}`} width="100%" role="img" aria-label="Evaluations per hour by verdict">
        {series.map((s, i) => {
          let y = h;
          const x = (i * w) / series.length + 2;
          return (
            <g key={s.hour}>
              {SERIES.map(([k, color]) => {
                const v = s[k] ?? 0;
                const bh = (v / max) * (h - 10);
                y -= bh;
                return v ? <rect key={k} x={x} y={y} width={bw} height={bh} fill={color} rx={2}><title>{`${k}: ${v}`}</title></rect> : null;
              })}
              {(i % Math.ceil(series.length / 8) === 0) && (
                <text x={x} y={h + 16} fontSize="10" fill="#606b85">
                  {new Date(s.hour).toLocaleTimeString([], { hour: "2-digit" })}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <Box display="flex" columnGap="space50" marginTop="space30">
        {SERIES.map(([k, c]) => (
          <Box key={k} display="flex" alignItems="center" columnGap="space20">
            <span style={{ width: 10, height: 10, borderRadius: 2, background: c, display: "inline-block" }} />
            <Text as="span" fontSize="fontSize20" color="colorTextWeak">{k.toLowerCase()}</Text>
          </Box>
        ))}
      </Box>
    </Box>
  );
}
