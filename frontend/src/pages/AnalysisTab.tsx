import { useEffect, useMemo, useState } from "react"
import { analyzeSession, ApiError } from "@/api/client"
import type { AnalyzeResponse, PlotData, Method, RepMetrics, SessionInfo } from "@/api/types"
import { fmt, fmtInt } from "@/lib/format"
import VyReadout from "@/components/VyReadout"

interface Props {
  sessions: SessionInfo[]
  selectedId: string | null
  onSelect: (id: string) => void
  onJumpToSessions: () => void
}

// Method labels reflect what the backend actually computes in
// src/velocity/velocity_metrics.py. Method D is not an EKF.
const METHOD_LEGEND: { m: Method; label: React.ReactNode }[] = [
  { m: "A", label: <>Raw a<sub>y</sub> · trapezoid integration.</> },
  { m: "B", label: <>ZUPT-only drift correction.</> },
  { m: "C", label: <>ZUPT + per-rep endpoint detrend.</> },
  { m: "D", label: <>0.1 Hz HP-accel + ZUPT + endpoint detrend. <i>Default.</i></> },
]

/**
 * Build an SVG path string for a per-rep vy(t) slice.
 * Plots the actual velocity samples between `chest_s` and `top_s` from
 * plot_data. Returns null if there aren't enough samples in the window.
 */
function buildRepSparkPath(
  plot: PlotData,
  chest_s: number,
  top_s: number,
  width = 120,
  height = 28,
  pad = 2,
): string | null {
  const t = plot.t
  const vy = plot.vy
  if (!t.length || !vy.length || top_s <= chest_s) return null
  // binary-ish linear scan; t is sorted ascending
  let i0 = 0
  while (i0 < t.length && t[i0] < chest_s) i0++
  let i1 = i0
  while (i1 < t.length && t[i1] <= top_s) i1++
  if (i1 - i0 < 3) return null
  const seg = vy.slice(i0, i1)
  const tseg = t.slice(i0, i1)
  const vMin = Math.min(...seg)
  const vMax = Math.max(...seg)
  const vRange = vMax - vMin || 1
  const tMin = tseg[0]
  const tMax = tseg[tseg.length - 1]
  const tRange = tMax - tMin || 1
  const innerW = width - pad * 2
  const innerH = height - pad * 2
  // downsample to ≤40 plotted points to keep SVG light
  const stride = Math.max(1, Math.floor(seg.length / 40))
  const pts: string[] = []
  for (let i = 0; i < seg.length; i += stride) {
    const x = pad + ((tseg[i] - tMin) / tRange) * innerW
    const y = pad + innerH - ((seg[i] - vMin) / vRange) * innerH
    pts.push(`${x.toFixed(1)},${y.toFixed(1)}`)
  }
  return `M${pts.join(" L")}`
}

function VelocityLossSummary({
  reps,
  bestNum,
}: {
  reps: RepMetrics[]
  bestNum: number | null
}) {
  const mpvs = reps.map((r) => r.mpv).filter((v): v is number => v != null)
  const best = mpvs.length ? Math.max(...mpvs) : null
  const last = mpvs.length ? mpvs[mpvs.length - 1] : null
  const vl = best && last ? (last - best) / best : null
  const avg = mpvs.length ? mpvs.reduce((a, b) => a + b, 0) / mpvs.length : null

  // Build the per-rep MPV trend path from actual data.
  const trendPath = useMemo(() => {
    if (mpvs.length < 2) return null
    const width = 120
    const height = 28
    const pad = 2
    const vMin = Math.min(...mpvs)
    const vMax = Math.max(...mpvs)
    const vRange = vMax - vMin || 1
    const innerW = width - pad * 2
    const innerH = height - pad * 2
    return (
      "M" +
      mpvs
        .map((v, i) => {
          const x = pad + (i / (mpvs.length - 1)) * innerW
          const y = pad + innerH - ((v - vMin) / vRange) * innerH
          return `${x.toFixed(1)},${y.toFixed(1)}`
        })
        .join(" L")
    )
  }, [mpvs])

  return (
    <div
      className="rep"
      style={{ background: "linear-gradient(180deg, rgba(180,255,120,.04), transparent)" }}
    >
      <div className="num" style={{ color: "var(--sig)" }}>
        <b style={{ color: "var(--sig)" }}>Σ</b>
        <span>{reps.length} reps</span>
      </div>
      <div className="mpv">
        {avg != null ? avg.toFixed(2) : "—"}
        <span className="u">mpv</span>
      </div>
      <svg
        className="spark"
        viewBox="0 0 120 28"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        {trendPath && (
          <path d={trendPath} fill="none" stroke="var(--bone)" strokeWidth={1.5} />
        )}
      </svg>
      <div className="row">
        <span>VL</span>
        <b style={{ color: vl != null && vl < -0.2 ? "var(--hot)" : "var(--ink-800)" }}>
          {vl != null ? `${(vl * 100).toFixed(0)}%` : "—"}
        </b>
      </div>
      <div className="row">
        <span>fatigue</span>
        <b>{vl != null && vl < -0.3 ? "high" : vl != null && vl < -0.15 ? "med" : "low"}</b>
      </div>
      <div className="tspan">
        <span>BEST</span>
        <b>R{bestNum ?? "—"}</b>
      </div>
    </div>
  )
}

export default function AnalysisTab({
  sessions,
  selectedId,
  onSelect,
  onJumpToSessions,
}: Props) {
  const [method, setMethod] = useState<Method>("D")
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const selected = useMemo(
    () => sessions.find((s) => s.session_id === selectedId) ?? null,
    [sessions, selectedId]
  )

  useEffect(() => {
    let cancelled = false
    async function run() {
      if (!selectedId) {
        setAnalysis(null)
        return
      }
      setLoading(true)
      setError(null)
      try {
        const res = await analyzeSession(selectedId, {
          method,
          include: ["velocity", "sticking"],
        })
        if (!cancelled) setAnalysis(res)
      } catch (e) {
        if (!cancelled) setError(e instanceof ApiError ? e.message : String(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    run()
    return () => {
      cancelled = true
    }
  }, [selectedId, method])

  if (!selected) {
    return (
      <section className="tabview">
        <div className="panel" style={{ padding: "48px 40px" }}>
          <div className="empty">
            No session selected. Upload or pick one from Sessions &amp; sets.
          </div>
          <div style={{ textAlign: "center", marginTop: 16 }}>
            <button className="btn" onClick={onJumpToSessions}>
              Go to Sessions
            </button>
          </div>
        </div>
      </section>
    )
  }

  const reps = analysis?.reps ?? []
  const bestRep = reps.length
    ? reps.reduce<RepMetrics | null>((best, r) => {
        if (r.mpv == null) return best
        if (!best || (best.mpv ?? -Infinity) < r.mpv) return r
        return best
      }, null)
    : null
  const bestNum = bestRep?.num ?? null

  // sticking: count reps flagged
  const stickingCount = (analysis?.sticking ?? []).filter((s) => s.has_sticking).length
  const flaggedRepNums = new Set(
    (analysis?.sticking ?? []).filter((s) => s.has_sticking).map((s) => s.num)
  )

  const peakCV = bestRep?.pcv ?? null
  const mpvs = reps.map((r) => r.mpv).filter((v): v is number => v != null)
  const vl = mpvs.length >= 2 ? (mpvs[mpvs.length - 1] - Math.max(...mpvs)) / Math.max(...mpvs) : null
  // Sticking-flagged rate: fraction of detected reps where the velocity
  // pipeline identified a true valley (drive peak → dip → recovery).
  // This is a real backend output — see src/sticking_point/sticking_point.py.
  const stickingRate = reps.length ? stickingCount / reps.length : 0

  // session timestamp formatting
  const ts = selected.uploaded_at
  const dt = new Date(ts)
  const dateLbl = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")} · ${String(dt.getHours()).padStart(2, "0")}:${String(dt.getMinutes()).padStart(2, "0")}`

  return (
    <section className="tabview">
      {/* session bar */}
      <div className="panel session-bar">
        <div className="sb-left">
          <div className="sess-head">
            <span className="id">{dateLbl}</span>
            {loading ? (
              <span className="chip" style={{ marginLeft: "auto" }}>analyzing…</span>
            ) : (
              <span className="chip live" style={{ marginLeft: "auto" }}>Analyzed</span>
            )}
          </div>
          <h2>
            Bench press{" "}
            {selected.load_lb != null && <em>@ {selected.load_lb} lb</em>}
          </h2>
          <div className="who">
            {selected.lifter ? (
              <>
                <b>{selected.lifter}</b> · IMU · {selected.filename}
              </>
            ) : (
              <>IMU · {selected.filename}</>
            )}
          </div>
        </div>

        <div className="sb-kv">
          <div>
            <div className="k">Load</div>
            <div className="v">
              {fmtInt(selected.load_lb)}
              <small>lb</small>
            </div>
          </div>
          <div>
            <div className="k">Reps detected</div>
            <div className="v">{reps.length || "—"}</div>
          </div>
          <div>
            <div className="k">Duration</div>
            <div className="v">
              {fmt(selected.duration_s, 1)}
              <small>s</small>
            </div>
          </div>
          <div>
            <div className="k">Sample rate</div>
            <div className="v">
              {fmtInt(selected.fs_hz)}
              <small>Hz</small>
            </div>
          </div>
        </div>

        <div className="sb-method">
          <div className="lbl">Velocity method</div>
          <div className="method-sel">
            {(["A", "B", "C", "D"] as Method[]).map((m) => (
              <button
                key={m}
                data-m={m}
                className={method === m ? "on" : ""}
                onClick={() => setMethod(m)}
              >
                {m}
              </button>
            ))}
          </div>
          <div className="method-legend">
            {METHOD_LEGEND.map((row) => (
              <div key={row.m} className={`row${row.m === method ? " on" : ""}`}>
                <b>{row.m}</b>
                <span>{row.label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {error && <div className="err">{error}</div>}

      {/* hero — velocity plot + telemetry */}
      <div className="hero">
        {analysis ? (
          <VyReadout analysis={analysis} method={method} bestRep={bestRep} />
        ) : (
          <div className="panel readout">
            <div className="panel-h">
              <span className="tit">Vertical velocity</span>
            </div>
            <div className="loading">
              {loading ? "analyzing…" : "waiting for session"}
            </div>
          </div>
        )}

        <div className="tele">
          <div className="panel">
            <div className="k">Peak concentric velocity</div>
            <div className="v">
              {peakCV != null ? peakCV.toFixed(2) : "—"}
              <span className="u">m/s</span>
            </div>
            <div className="delta">rep {bestNum ?? "—"} · method {method}</div>
            <div className="bar">
              <i style={{ width: `${Math.min(100, (peakCV ?? 0) * 80)}%` }} />
            </div>
          </div>

          <div className="panel">
            <div className="k">Velocity loss · set</div>
            <div className="v">
              {vl != null ? `${(vl * 100).toFixed(0)}` : "—"}
              <span className="u">%</span>
            </div>
            <div className={`delta ${vl != null && vl < -0.2 ? "down" : ""}`}>
              {vl == null
                ? "waiting"
                : vl < -0.2
                ? "above 20% target"
                : "within 20% target"}
            </div>
            <div className="bar">
              <i
                style={{
                  width: `${Math.min(100, Math.abs((vl ?? 0) * 100))}%`,
                  background: vl != null && vl < -0.2 ? "var(--hot)" : "var(--sig)",
                }}
              />
            </div>
          </div>

          <div className="panel">
            <div className="k">Sticking-flagged reps</div>
            <div className="v">
              {stickingCount}
              <span className="u">/ {reps.length || "—"}</span>
            </div>
            <div className={`delta ${stickingRate > 0.5 ? "down" : ""}`}>
              {reps.length === 0
                ? "waiting"
                : stickingCount === 0
                ? "no distinct valley after drive"
                : `${(stickingRate * 100).toFixed(0)}% with post-drive valley`}
            </div>
            <div className="bar">
              <i
                style={{
                  width: `${Math.round(stickingRate * 100)}%`,
                  background: stickingRate > 0.5 ? "var(--hot)" : "var(--sig)",
                }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* rep grid + bar path */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "2fr 1.1fr",
          gap: 16,
          marginTop: 28,
        }}
      >
        <div className="panel reps">
          <div className="panel-h">
            <span className="tit">
              Repetitions · {reps.length} of {reps.length} detected
            </span>
            <span style={{ color: "var(--ink-600)" }}>
              sign-change counter · post-motion + rerack-gyro filters
            </span>
            <span className="r">
              <span className="chip live">{stickingCount === 0 ? "0 errors" : `${stickingCount} flag`}</span>
            </span>
          </div>

          {reps.length === 0 ? (
            <div className="empty">no reps in analysis response</div>
          ) : (
            <div className="grid">
              {reps.slice(0, 5).map((r, i) => {
                const nextChest = reps[i + 1]?.chest_s ?? null
                const flagged = flaggedRepNums.has(r.num)
                const sparkD = analysis
                  ? buildRepSparkPath(analysis.plot_data, r.chest_s, r.top_s)
                  : null
                return (
                  <div
                    key={r.num}
                    className={`rep${r.num === bestNum ? " best" : ""}${flagged ? " flag" : ""}`}
                    data-rep={r.num}
                  >
                    <div className="num">
                      <b>R{r.num}</b>
                    </div>
                    <div className="mpv">
                      {r.mpv != null ? r.mpv.toFixed(2) : "—"}
                      <span className="u">mpv</span>
                    </div>
                    <svg
                      className="spark"
                      viewBox="0 0 120 28"
                      preserveAspectRatio="none"
                    >
                      {sparkD && (
                        <path
                          d={sparkD}
                          fill="none"
                          stroke="var(--sig)"
                          strokeWidth={r.num === bestNum ? 2 : 1.5}
                        />
                      )}
                    </svg>
                    <div className="row">
                      <span>peak</span>
                      <b>{fmt(r.pcv, 2)} m/s</b>
                    </div>
                    <div className="row">
                      <span>tROM</span>
                      <b>{fmt(r.duration_s, 2)} s</b>
                    </div>
                    <div className="tspan">
                      <span>t</span>
                      <b>
                        {r.chest_s.toFixed(1)} –{" "}
                        {(nextChest ?? r.chest_s + r.duration_s).toFixed(1)} s
                      </b>
                    </div>
                  </div>
                )
              })}
              {reps.length > 0 && <VelocityLossSummary reps={reps} bestNum={bestNum} />}
              {/* fill to 6 cells to keep grid borders clean */}
              {Array.from({ length: Math.max(0, 5 - Math.min(reps.length, 5)) }).map(
                (_, i) => (
                  <div key={`fill-${i}`} className="rep" style={{ opacity: 0.2 }}>
                    <div className="num">
                      <b>—</b>
                    </div>
                  </div>
                )
              )}
            </div>
          )}
        </div>

        {/* bar path — 2D reconstruction pending backend EKF output */}
        <div className="panel barpath">
          <div className="panel-h">
            <span className="tit">Bar path · sagittal</span>
            <span className="r">
              <span
                className="chip"
                title="2D path reconstruction requires integrating accelerometer + gyro into world-frame position. Not yet implemented in the Python backend — firmware emits raw IMU only. The ROM / duration / propulsive-fraction values below come from the 1D velocity pipeline and are real."
              >
                in development
              </span>
              <span className="chip">{reps.length} reps</span>
            </span>
          </div>
          <div className="barpath-viz">
            <div className="barpath-legend">
              <div className="row">
                <span className="sw" style={{ background: "var(--ink-600)" }} />
                <span>plot area (pending EKF)</span>
              </div>
            </div>
            <svg viewBox="0 0 520 360" preserveAspectRatio="xMidYMid meet">
              {/* structural grid kept so the real plot will drop in unchanged */}
              <g stroke="#161b23" strokeWidth="1">
                <line x1="0" y1="60" x2="520" y2="60" />
                <line x1="0" y1="120" x2="520" y2="120" />
                <line x1="0" y1="180" x2="520" y2="180" />
                <line x1="0" y1="240" x2="520" y2="240" />
                <line x1="0" y1="300" x2="520" y2="300" />
                <line x1="80" y1="0" x2="80" y2="360" />
                <line x1="160" y1="0" x2="160" y2="360" />
                <line x1="240" y1="0" x2="240" y2="360" />
                <line x1="320" y1="0" x2="320" y2="360" />
                <line x1="400" y1="0" x2="400" y2="360" />
              </g>

              {/*
                PLUG-IN POINT. When the backend adds per-rep 2D path data
                (e.g. plot_data.path_x[], plot_data.path_y[] or a dedicated
                /api/sessions/:id/path endpoint), replace the placeholder
                block below with a map over rep paths:

                  rep_paths.map((rep, i) => (
                    <path
                      key={rep.num}
                      d={buildPath2D(rep.x_cm, rep.y_cm)}
                      stroke="var(--sig)"
                      strokeWidth={rep.num === bestNum ? 2.4 : 1.6}
                      opacity={rep.num === bestNum ? 1 : 0.5}
                      fill="none"
                    />
                  ))

                The grid above + footer below don't need to change.
              */}
              <g transform="translate(260 180)" fontFamily="JetBrains Mono, monospace">
                <text
                  x="0"
                  y="-18"
                  textAnchor="middle"
                  fontSize="11"
                  fill="var(--hot)"
                  letterSpacing="1.6"
                >
                  2D PATH RECONSTRUCTION
                </text>
                <text
                  x="0"
                  y="4"
                  textAnchor="middle"
                  fontSize="11"
                  fill="var(--hot)"
                  letterSpacing="1.6"
                >
                  STILL IN DEVELOPMENT
                </text>
                <text
                  x="0"
                  y="28"
                  textAnchor="middle"
                  fontSize="9"
                  fill="var(--ink-600)"
                  letterSpacing="1.2"
                >
                  awaiting EKF position output from backend
                </text>
              </g>

              <g fontFamily="JetBrains Mono, monospace" fontSize="10" fill="#5a6678" letterSpacing="1.4">
                <text x="10" y="14">Y (cm)</text>
                <text x="470" y="344">X (cm)</text>
              </g>
            </svg>
          </div>
          <div className="barpath-foot">
            <div>
              <div className="k">ROM</div>
              <div className="v">
                {bestRep?.rom_m != null ? (bestRep.rom_m * 100).toFixed(1) : "—"} cm
              </div>
            </div>
            <div>
              <div className="k">Concentric dur.</div>
              <div className="v">{fmt(bestRep?.duration_s, 2)} s</div>
            </div>
            <div>
              <div className="k">Propulsive frac.</div>
              <div className="v">
                {bestRep?.propulsive_frac != null
                  ? `${(bestRep.propulsive_frac * 100).toFixed(0)}%`
                  : "—"}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* other sessions — inline picker */}
      {sessions.length > 1 && (
        <div style={{ marginTop: 28 }}>
          <div
            style={{
              fontFamily: "var(--f-mono)",
              fontSize: 11,
              letterSpacing: ".18em",
              textTransform: "uppercase",
              color: "var(--ink-700)",
              marginBottom: 10,
            }}
          >
            Switch set
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {sessions.map((s) => (
              <button
                key={s.session_id}
                className={`chip${s.session_id === selectedId ? " live" : ""}`}
                style={{
                  cursor: "pointer",
                  background: s.session_id === selectedId ? undefined : "transparent",
                }}
                onClick={() => onSelect(s.session_id)}
              >
                {s.lifter ?? "—"} · {s.load_lb ?? "—"} lb · {s.filename.slice(0, 28)}
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
