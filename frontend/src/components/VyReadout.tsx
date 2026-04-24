import { useMemo } from "react"
import {
  Area,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import type { AnalyzeResponse, Method, RepBoundary, RepMetrics } from "@/api/types"
import { fmt } from "@/lib/format"

interface Props {
  analysis: AnalyzeResponse
  method: Method
  bestRep: RepMetrics | null
}

interface Sample {
  t: number
  vy: number
  gyroScaled: number
}

export default function VyReadout({ analysis, method, bestRep }: Props) {
  const { plot_data, rep_boundaries, reps } = analysis

  const samples = useMemo<Sample[]>(() => {
    const n = Math.min(plot_data.t.length, plot_data.vy.length)
    const g = plot_data.gyro_mag ?? []
    // Downsample to ≤900 points so Recharts renders smoothly
    const stride = Math.max(1, Math.floor(n / 900))
    const acc: Sample[] = []
    for (let i = 0; i < n; i += stride) {
      acc.push({
        t: plot_data.t[i],
        vy: plot_data.vy[i],
        gyroScaled: (g[i] ?? 0) * 0.3,
      })
    }
    return acc
  }, [plot_data])

  const tMax = samples.length ? samples[samples.length - 1].t : 1
  const yMin = -0.6
  const yMax = 1.2

  const bestNum = bestRep?.num ?? null

  // build per-rep peak points from reps if available
  const peakDots = useMemo(() => {
    if (!reps || !reps.length) return [] as { t: number; vy: number; num: number }[]
    const dots: { t: number; vy: number; num: number }[] = []
    for (const r of reps) {
      if (r.tpv_s == null || r.pcv == null) continue
      // tpv is relative to rep start; absolute time = chest_s + tpv
      const t = r.chest_s + r.tpv_s
      dots.push({ t, vy: r.pcv, num: r.num })
    }
    return dots
  }, [reps])

  const ticks = useMemo(() => {
    const n = 5
    return Array.from({ length: n }, (_, i) => (tMax / (n - 1)) * i)
  }, [tMax])

  return (
    <div className="readout panel">
      <div className="panel-h">
        <span className="tit">
          Vertical velocity · V<sub>y</sub>(t)
        </span>
        <span className="r">
          <span className="chip">Method {method}</span>
          <span className="chip">
            {rep_boundaries.length} {rep_boundaries.length === 1 ? "rep" : "reps"}
          </span>
        </span>
      </div>

      <div className="readout-title">
        <div>
          <div className="lbl">Best mean propulsive velocity</div>
          <div className="big">
            {bestRep?.mpv != null ? bestRep.mpv.toFixed(2) : "—"}
            <span className="u">m/s</span>
          </div>
        </div>
        <div className="sub">
          {bestRep ? (
            <>
              rep <b>{bestRep.num}</b> · peak {fmt(bestRep.pcv, 2)} m/s
              <br />
              concentric {fmt(bestRep.duration_s, 2)} s
            </>
          ) : (
            "—"
          )}
        </div>
      </div>

      <div className="wave-legend">
        <div className="row">
          <span className="sw" style={{ background: "var(--sig)" }} />
          <span>
            V<sub>y</sub> · m/s
          </span>
        </div>
        <div className="row">
          <span className="sw" style={{ background: "var(--ink-600)" }} />
          <span>|ω| rad/s ×0.3</span>
        </div>
      </div>

      <div className="wave-wrap">
        <div className="yaxis">
          <span className="unit">m/s</span>
          <span className="tick" style={{ top: "8%" }}>+1.0</span>
          <span className="tick" style={{ top: "30%" }}>+0.5</span>
          <span className="tick" style={{ top: "53%" }}>&nbsp;0.0</span>
          <span className="tick" style={{ top: "75%" }}>−0.5</span>
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={samples} margin={{ top: 10, right: 10, left: 0, bottom: 10 }}>
            <defs>
              <linearGradient id="vyFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="oklch(0.88 0.18 125)" stopOpacity={0.3} />
                <stop offset="100%" stopColor="oklch(0.88 0.18 125)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              type="number"
              dataKey="t"
              domain={[0, tMax]}
              hide
            />
            <YAxis type="number" domain={[yMin, yMax]} hide />

            {/* rep boundary bands — alternate shade */}
            {rep_boundaries.map((r: RepBoundary, i: number) => (
              <ReferenceArea
                key={`band-${r.num}`}
                x1={r.chest_s}
                x2={r.lockout_s}
                y1={yMin}
                y2={yMax}
                fill={r.num === bestNum ? "oklch(0.88 0.18 125)" : "#ffffff"}
                fillOpacity={r.num === bestNum ? 0.06 : i % 2 === 0 ? 0.015 : 0.03}
                stroke="none"
              />
            ))}

            {/* rep boundary vertical dashes */}
            {rep_boundaries.map((r) => (
              <ReferenceLine
                key={`div-${r.num}`}
                x={r.chest_s}
                stroke="var(--ink-400)"
                strokeDasharray="1 4"
                strokeWidth={1}
              />
            ))}

            {/* zero velocity */}
            <ReferenceLine y={0} stroke="var(--ink-500)" strokeDasharray="2 4" />

            {/* UNRACK / RE-RACK markers */}
            <ReferenceLine
              x={0}
              stroke="var(--hot)"
              strokeWidth={1.5}
              label={{
                value: "UNRACK",
                position: "insideTopLeft",
                fill: "oklch(0.78 0.18 55)",
                fontSize: 9,
                letterSpacing: "1.4px",
                fontFamily: "JetBrains Mono, monospace",
              }}
            />
            <ReferenceLine
              x={tMax}
              stroke="var(--hot)"
              strokeWidth={1.5}
              label={{
                value: "RE-RACK",
                position: "insideTopRight",
                fill: "oklch(0.78 0.18 55)",
                fontSize: 9,
                letterSpacing: "1.4px",
                fontFamily: "JetBrains Mono, monospace",
              }}
            />

            {/* gyro magnitude */}
            <Line
              type="monotone"
              dataKey="gyroScaled"
              stroke="var(--ink-600)"
              strokeWidth={1.25}
              strokeOpacity={0.55}
              dot={false}
              isAnimationActive={false}
            />

            {/* Vy area + line */}
            <Area
              type="monotone"
              dataKey="vy"
              stroke="none"
              fill="url(#vyFill)"
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="vy"
              stroke="var(--sig)"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />

            {/* rep peaks */}
            {peakDots.map((d) => (
              <ReferenceDot
                key={`peak-${d.num}`}
                x={d.t}
                y={d.vy}
                r={d.num === bestNum ? 4.5 : 3.5}
                fill="var(--sig)"
                stroke={d.num === bestNum ? "var(--bone)" : undefined}
                strokeWidth={d.num === bestNum ? 1 : 0}
              />
            ))}

            <Tooltip
              cursor={{ stroke: "var(--sig)", strokeDasharray: "2 3", strokeOpacity: 0.6 }}
              contentStyle={{
                background: "rgba(10,13,17,.95)",
                border: "1px solid var(--ink-400)",
                borderRadius: 2,
                fontFamily: "var(--f-mono)",
                fontSize: 11,
                color: "var(--ink-900)",
              }}
              labelFormatter={(v) => `t ${Number(v).toFixed(2)} s`}
              formatter={(v) => Number(v).toFixed(3)}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="wave-foot">
        {ticks.map((t, i) => (
          <span key={i}>{t.toFixed(1)} s</span>
        ))}
      </div>
    </div>
  )
}
