import { useMemo } from "react"
import {
  CartesianGrid,
  Legend,
  Line,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts"
import type { EstimatorOut, SessionSummary } from "@/api/types"

const ESTIMATOR_COLORS: Record<string, string> = {
  M1_MPV_lin: "#2563eb",
  M2_MPV_exp: "#7c3aed",
  M3_MPV_last: "#059669",
  M4_PCV_lin: "#dc2626",
  M5_Bosco: "#f59e0b",
  M6_VL10: "#0891b2",
}

interface Props {
  sessions: SessionSummary[]
  estimators: EstimatorOut[]
}

export function LvpScatter({ sessions, estimators }: Props) {
  const pts = useMemo(
    () =>
      sessions
        .filter((s) => s.best_mpv != null)
        .map((s) => ({ x: s.best_mpv as number, y: s.load_lb, name: s.name })),
    [sessions]
  )

  const xMax = Math.max(1.2, ...pts.map((p) => p.x + 0.1))
  const validEstimatorYs = estimators
    .filter((e) => e.valid && e.one_rm_lb != null)
    .map((e) => e.one_rm_lb as number)
  const loadYs = pts.map((p) => p.y)
  const yMax = Math.ceil(
    (Math.max(...loadYs, ...validEstimatorYs, 200) * 1.1) / 50
  ) * 50

  const linearFits = estimators
    .filter(
      (e) =>
        e.valid &&
        e.slope != null &&
        e.intercept != null &&
        (e.name === "M1_MPV_lin" || e.name === "M4_PCV_lin")
    )
    .map((e) => {
      const data = [0.1, xMax].map((x) => ({
        x,
        y: (e.slope as number) * x + (e.intercept as number),
      }))
      return { name: e.name, data, color: ESTIMATOR_COLORS[e.name] }
    })

  return (
    <div className="h-[360px] w-full">
      <ResponsiveContainer>
        <ScatterChart margin={{ top: 16, right: 24, left: 0, bottom: 16 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis
            type="number"
            dataKey="x"
            name="MPV"
            domain={[0, xMax]}
            tickFormatter={(v) => v.toFixed(2)}
            label={{ value: "best MPV (m/s)", position: "insideBottom", offset: -5 }}
            className="text-xs"
          />
          <YAxis
            type="number"
            dataKey="y"
            name="load"
            domain={[0, yMax]}
            tickFormatter={(v) => Number(v).toFixed(0)}
            label={{ value: "load (lb)", angle: -90, position: "insideLeft" }}
            className="text-xs"
          />
          <ZAxis range={[80, 80]} />
          <Tooltip
            cursor={{ strokeDasharray: "3 3" }}
            formatter={(value, key) => {
              const n = Number(value)
              if (key === "x") return n.toFixed(3)
              return n.toFixed(1)
            }}
          />
          <Legend verticalAlign="top" height={24} />
          {linearFits.map((f) => (
            <Line
              key={f.name}
              data={f.data}
              dataKey="y"
              type="linear"
              dot={false}
              stroke={f.color}
              strokeWidth={2}
              name={f.name}
              legendType="line"
              isAnimationActive={false}
            />
          ))}
          <Scatter name="Sessions" data={pts} fill="#111827" />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  )
}
