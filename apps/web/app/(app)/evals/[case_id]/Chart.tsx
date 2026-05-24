"use client";

import { useMemo } from "react";

/**
 * Pure-SVG line chart — no chart library.
 *
 * One viewport, multiple series. X is record index (left=oldest, right=newest).
 * Y is 0..10 (we map pass_rate 0..1 → 0..10 so judge scores and pass_rate
 * share an axis).
 */

export interface ChartSeries {
  name: string;
  color: string;
  /** Pairs of (x, y in 0..10). NaN values become gaps. */
  points: Array<{ x: number; y: number }>;
}

export function LineChart({
  width = 720,
  height = 220,
  series,
  xAxisLabels = [],
}: {
  width?: number;
  height?: number;
  series: ChartSeries[];
  xAxisLabels?: string[];
}) {
  const padding = { top: 12, right: 80, bottom: 28, left: 36 };
  const plotW = width - padding.left - padding.right;
  const plotH = height - padding.top - padding.bottom;

  const maxX = useMemo(
    () => Math.max(0, ...series.flatMap((s) => s.points.map((p) => p.x))),
    [series],
  );

  // Y axis is 0..10 fixed (judge scale + pass_rate*10).
  const xFor = (x: number) => padding.left + (maxX > 0 ? (x / maxX) * plotW : plotW / 2);
  const yFor = (y: number) => padding.top + plotH - (y / 10) * plotH;

  const yTicks = [0, 2, 4, 6, 8, 10];

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-auto block"
      preserveAspectRatio="xMidYMid meet"
    >
      {/* Y grid + labels */}
      {yTicks.map((t) => (
        <g key={t}>
          <line
            x1={padding.left}
            x2={padding.left + plotW}
            y1={yFor(t)}
            y2={yFor(t)}
            stroke="var(--line)"
            strokeDasharray={t === 0 ? "" : "2 4"}
          />
          <text
            x={padding.left - 6}
            y={yFor(t) + 3}
            textAnchor="end"
            fontSize="9"
            fontFamily="var(--font-mono)"
            fill="var(--ink-faint)"
          >
            {t}
          </text>
        </g>
      ))}

      {/* X axis labels (sparse — every Nth) */}
      {xAxisLabels.length > 0 &&
        xAxisLabels.map((label, i) => {
          // print 4 labels max
          const step = Math.max(1, Math.ceil(xAxisLabels.length / 4));
          if (i % step !== 0 && i !== xAxisLabels.length - 1) return null;
          return (
            <text
              key={i}
              x={xFor(i)}
              y={padding.top + plotH + 16}
              textAnchor="middle"
              fontSize="9"
              fontFamily="var(--font-mono)"
              fill="var(--ink-faint)"
            >
              {label}
            </text>
          );
        })}

      {/* Series */}
      {series.map((s) => (
        <g key={s.name}>
          <path
            d={s.points
              .filter((p) => !Number.isNaN(p.y))
              .map((p, i) => `${i === 0 ? "M" : "L"} ${xFor(p.x)} ${yFor(p.y)}`)
              .join(" ")}
            stroke={s.color}
            strokeWidth="1.5"
            fill="none"
          />
          {s.points
            .filter((p) => !Number.isNaN(p.y))
            .map((p, i) => (
              <circle
                key={i}
                cx={xFor(p.x)}
                cy={yFor(p.y)}
                r="2.5"
                fill={s.color}
              />
            ))}
        </g>
      ))}

      {/* Legend */}
      {series.map((s, i) => (
        <g key={s.name} transform={`translate(${padding.left + plotW + 8}, ${padding.top + i * 16})`}>
          <line x1="0" x2="12" y1="6" y2="6" stroke={s.color} strokeWidth="1.5" />
          <text
            x="16"
            y="9"
            fontSize="10"
            fontFamily="var(--font-mono)"
            fill="var(--ink-soft)"
          >
            {s.name}
          </text>
        </g>
      ))}
    </svg>
  );
}
