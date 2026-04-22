import { useMemo } from "react"
import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import type { PlotData, RepBoundary, StickingPoint } from "@/api/types"

interface Props {
  plot: PlotData
  boundaries: RepBoundary[]
  sticking?: StickingPoint[]
  stride?: number
}

interface PlotPoint {
  t: number
  vy: number
}

export function VelocityPlot({ plot, boundaries, sticking, stride }: Props) {
  const data = useMemo<PlotPoint[]>(() => {
    const n = plot.t.length
    const target = 1500
    const step = stride ?? Math.max(1, Math.floor(n / target))
    const out: PlotPoint[] = []
    for (let i = 0; i < n; i += step) {
      out.push({ t: plot.t[i], vy: plot.vy[i] })
    }
    return out
  }, [plot, stride])

  return (
    <div className="h-[380px] w-full">
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 10, right: 24, left: 0, bottom: 10 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          <XAxis
            dataKey="t"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(v) => v.toFixed(1)}
            label={{ value: "Time (s)", position: "insideBottom", offset: -5 }}
            className="text-xs"
          />
          <YAxis
            tickFormatter={(v) => v.toFixed(2)}
            label={{
              value: "vertical velocity (m/s)",
              angle: -90,
              position: "insideLeft",
              offset: 10,
            }}
            className="text-xs"
          />
          <Tooltip
            formatter={(value) => Number(value).toFixed(3)}
            labelFormatter={(label) => `t = ${Number(label).toFixed(2)} s`}
          />
          <Legend verticalAlign="top" height={24} />
          <ReferenceLine y={0} stroke="currentColor" opacity={0.4} />
          <Line
            type="monotone"
            dataKey="vy"
            name="v_y"
            stroke="#2563eb"
            dot={false}
            strokeWidth={1.5}
            isAnimationActive={false}
          />
          {boundaries.flatMap((b) => [
            <ReferenceLine
              key={`c-${b.num}`}
              x={b.chest_s}
              stroke="#10b981"
              strokeDasharray="2 2"
              label={{ value: `#${b.num}`, position: "top", fill: "#10b981", fontSize: 10 }}
            />,
            <ReferenceLine
              key={`l-${b.num}`}
              x={b.lockout_s}
              stroke="#ef4444"
              strokeDasharray="2 2"
            />,
          ])}
          {sticking
            ?.filter((sp) => sp.has_sticking && sp.sp_t != null && sp.sp_v != null)
            .map((sp) => (
              <ReferenceDot
                key={`sp-${sp.num}`}
                x={sp.sp_t as number}
                y={sp.sp_v as number}
                r={5}
                fill="#f59e0b"
                stroke="#b45309"
                strokeWidth={1}
              />
            ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
