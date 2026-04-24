import { useEffect, useMemo, useState } from "react"
import { analyzeSession, ApiError, getBarPath } from "@/api/client"
import type {
  AnalyzeResponse,
  BarPathResponse,
  Method,
  RepMetrics,
  SessionInfo,
} from "@/api/types"
import { fmt, fmtInt } from "@/lib/format"
import VyReadout from "@/components/VyReadout"

interface Props {
  sessions: SessionInfo[]
  selectedId: string | null
  onSelect: (id: string) => void
  onJumpToSessions: () => void
}

const METHOD_LEGEND: { m: Method; label: React.ReactNode }[] = [
  { m: "A", label: <>Raw a<sub>y</sub> · single integration.</> },
  { m: "B", label: <>High-pass a<sub>y</sub> + zero-vel update.</> },
  { m: "C", label: <>Gravity-comp · rep-segmented.</> },
  { m: "D", label: <>EKF accel+gyro fusion. <i>Default.</i></> },
]

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
        <path
          d="M0,4 L24,6 L48,8 L72,14 L96,20 L120,24"
          fill="none"
          stroke="var(--bone)"
          strokeWidth={1.5}
        />
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
  const [barPath, setBarPath] = useState<BarPathResponse | null>(null)
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
        setBarPath(null)
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

  // Bar-path reconstruction is independent of the velocity method and
  // runs once per selected session. Failures here are non-fatal: the
  // panel falls back to the ROM/duration metrics computed by analyze.
  useEffect(() => {
    let cancelled = false
    async function run() {
      if (!selectedId) {
        setBarPath(null)
        return
      }
      try {
        const res = await getBarPath(selectedId)
        if (!cancelled) setBarPath(res)
      } catch {
        if (!cancelled) setBarPath(null)
      }
    }
    run()
    return () => {
      cancelled = true
    }
  }, [selectedId])

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
  const repCountConf = reps.length
    ? reps.filter((r) => r.mpv != null && r.pcv != null).length / reps.length
    : 0

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
            <div className="k">Rep-count confidence</div>
            <div className="v">{repCountConf.toFixed(2)}</div>
            <div className="delta">
              {reps.length} of {reps.length} reps pass filters
              {stickingCount > 0 && ` · ${stickingCount} flagged`}
            </div>
            <div className="bar">
              <i style={{ width: `${Math.round(repCountConf * 100)}%` }} />
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
                      <path
                        d={`M0,22 L15,24 L30,26 L45,${20 - (r.mpv ?? 0) * 8} L60,${14 - (r.pcv ?? 0) * 10} L75,${10 - (r.pcv ?? 0) * 10} L90,${18 - (r.mpv ?? 0) * 8} L105,22 L120,24`}
                        fill="none"
                        stroke="var(--sig)"
                        strokeWidth={r.num === bestNum ? 2 : 1.5}
                      />
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

        {/* bar path */}
        <div className="panel barpath">
          <div className="panel-h">
            <span className="tit">Bar path · sagittal</span>
            <span className="r">
              {barPath ? (
                <span className="chip live" title="Reconstructed from IMU linear acceleration with per-rep endpoint-anchored integration.">
                  reconstructed
                </span>
              ) : (
                <span className="chip" title="Bar-path reconstruction unavailable for this session.">
                  unavailable
                </span>
              )}
              <span className="chip">{barPath?.n_reps ?? reps.length} reps</span>
            </span>
          </div>
          <div className="barpath-viz">
            <div className="barpath-legend">
              <div className="row">
                <span className="sw" style={{ background: "var(--sig)" }} />
                <span>best rep</span>
              </div>
              <div className="row">
                <span className="sw" style={{ background: "var(--bone)", opacity: 0.5 }} />
                <span>other reps</span>
              </div>
            </div>
            <svg viewBox="0 0 520 360" preserveAspectRatio="xMidYMid meet">
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
              <line x1="260" y1="0" x2="260" y2="360" stroke="#2a323f" strokeDasharray="1 6" />
              {/* real per-rep bar paths. Axes:
                    svg_y = 120 − z_cm · 3   (z=0 at top, z=−40 mid)
                    svg_x = 260 + x_cm · 8   (x=0 centered)                  */}
              {barPath && barPath.reps.length > 0 && (() => {
                const PX_PER_CM_Y = 3
                const PX_PER_CM_X = 8
                const ORIG_Y = 120
                const ORIG_X = 260
                const toPath = (xs: number[], zs: number[]) =>
                  xs
                    .map((xm, i) => {
                      const X = ORIG_X + xm * 100 * PX_PER_CM_X
                      const Y = ORIG_Y - zs[i] * 100 * PX_PER_CM_Y
                      return `${i === 0 ? "M" : "L"} ${X.toFixed(1)},${Y.toFixed(1)}`
                    })
                    .join(" ")
                const bestBp = bestNum
                  ? barPath.reps.find((r) => r.num === bestNum) ?? null
                  : null
                return (
                  <>
                    <g fill="none" stroke="var(--bone)" strokeWidth={1.3} opacity={0.45}>
                      {barPath.reps
                        .filter((r) => !bestBp || r.num !== bestBp.num)
                        .slice(0, 8)
                        .map((r) => (
                          <path key={`bp-${r.num}`} d={toPath(r.x_m, r.z_m)} />
                        ))}
                    </g>
                    {bestBp && (
                      <g fill="none" stroke="var(--sig)" strokeWidth={2.4}>
                        <path d={toPath(bestBp.x_m, bestBp.z_m)} />
                        <circle
                          cx={ORIG_X + bestBp.x_m[0] * 100 * PX_PER_CM_X}
                          cy={ORIG_Y - bestBp.z_m[0] * 100 * PX_PER_CM_Y}
                          r={3}
                          fill="var(--sig)"
                        />
                        <circle
                          cx={
                            ORIG_X +
                            bestBp.x_m[bestBp.chest_idx] * 100 * PX_PER_CM_X
                          }
                          cy={
                            ORIG_Y -
                            bestBp.z_m[bestBp.chest_idx] * 100 * PX_PER_CM_Y
                          }
                          r={3}
                          fill="var(--sig)"
                        />
                      </g>
                    )}
                  </>
                )
              })()}
              {!barPath && (
                <text
                  x={260}
                  y={184}
                  textAnchor="middle"
                  fontFamily="JetBrains Mono, monospace"
                  fontSize={11}
                  fill="#5a6678"
                >
                  bar-path reconstruction unavailable
                </text>
              )}
              <g fontFamily="JetBrains Mono, monospace" fontSize="10" fill="#5a6678" letterSpacing="1.4">
                <text x="10" y="14">Y (cm)</text>
                <text x="10" y="64">+20</text>
                <text x="10" y="124">&nbsp; 0</text>
                <text x="10" y="184">-20</text>
                <text x="10" y="244">-40</text>
                <text x="10" y="304">-60</text>
                <text x="470" y="344">X (cm)</text>
                <text x="256" y="344" fill="#8892a4">0</text>
              </g>
            </svg>
          </div>
          <div className="barpath-foot">
            <div>
              <div className="k">ROM</div>
              <div className="v">
                {(() => {
                  const bestBp = barPath && bestNum
                    ? barPath.reps.find((r) => r.num === bestNum)
                    : null
                  const rom_m = bestBp?.rom_m ?? bestRep?.rom_m ?? null
                  return rom_m != null ? (rom_m * 100).toFixed(1) : "—"
                })()}{" "}
                cm
              </div>
            </div>
            <div>
              <div className="k">Forward drift</div>
              <div className="v">
                {(() => {
                  const bestBp = barPath && bestNum
                    ? barPath.reps.find((r) => r.num === bestNum)
                    : null
                  return bestBp?.peak_x_dev_m != null
                    ? `${(bestBp.peak_x_dev_m * 100).toFixed(1)} cm`
                    : "—"
                })()}
              </div>
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
