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
  const [selectedBarRep, setSelectedBarRep] = useState<number | "all">("all")
  const [techniqueMode, setTechniqueMode] = useState<"ellipse" | "j">("ellipse")
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
        if (!cancelled) {
          setBarPath(res)
          setSelectedBarRep("all")
        }
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
              {reps.map((r, i) => {
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
              <VelocityLossSummary reps={reps} bestNum={bestNum} />
              {/* fill to a complete row of 6 to keep grid borders clean */}
              {Array.from({ length: (6 - ((reps.length + 1) % 6)) % 6 }).map(
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
              {barPath && barPath.reps.length > 0 && (
                <select
                  className="bp-rep-select"
                  value={selectedBarRep === "all" ? "all" : String(selectedBarRep)}
                  onChange={(e) =>
                    setSelectedBarRep(
                      e.target.value === "all" ? "all" : Number(e.target.value)
                    )
                  }
                  aria-label="Select rep to display"
                >
                  <option value="all">all reps</option>
                  {barPath.reps.map((r) => (
                    <option key={r.num} value={r.num}>
                      R{r.num}
                    </option>
                  ))}
                </select>
              )}
              {barPath && selectedBarRep !== "all" && (
                <select
                  className="bp-rep-select"
                  value={techniqueMode}
                  onChange={(e) =>
                    setTechniqueMode(e.target.value as "ellipse" | "j")
                  }
                  aria-label="Reference technique shape"
                  title="Reference technique shape"
                >
                  <option value="ellipse">ellipse</option>
                  <option value="j">J-curve</option>
                </select>
              )}
            </span>
          </div>
          <div className="barpath-viz">
            <div className="barpath-legend">
              <div className="row">
                <span className="sw" style={{ background: "var(--sig)" }} />
                <span>{selectedBarRep === "all" ? "best rep" : `R${selectedBarRep}`}</span>
              </div>
              {selectedBarRep === "all" ? (
                <div className="row">
                  <span className="sw" style={{ background: "var(--bone)", opacity: 0.5 }} />
                  <span>other reps</span>
                </div>
              ) : (
                <div className="row">
                  <span
                    className="sw"
                    style={{
                      background:
                        "repeating-linear-gradient(90deg, var(--hot) 0 4px, transparent 4px 7px)",
                    }}
                  />
                  <span>{techniqueMode === "j" ? "reference J-curve" : "reference ellipse"}</span>
                </div>
              )}
            </div>
            <svg viewBox="0 0 520 360" preserveAspectRatio="xMidYMid meet">
              {barPath && barPath.reps.length > 0 ? (() => {
                const visible =
                  selectedBarRep === "all"
                    ? barPath.reps
                    : barPath.reps.filter((r) => r.num === selectedBarRep)
                if (visible.length === 0) return null

                // Reference technique shape — single rep only.
                // "ellipse" sweeps tau ∈ [0, 2π] for a closed loop:
                // eccentric leg forward of the diagonal, concentric
                // leg behind it. "j" sweeps tau ∈ [0, π] for the
                // descent half only — the iconic open J. Forward
                // direction follows the sign of the rep's own chest x
                // (typically -X per the IMU convention).
                let optimal: { x: number[]; z: number[] } | null = null
                if (selectedBarRep !== "all" && visible.length === 1) {
                  const repSel = visible[0]
                  const ROM_M = Math.max(repSel.rom_m, 0.05)
                  const chestX = repSel.x_m[repSel.chest_idx] ?? 0
                  const xSign = chestX < 0 ? -1 : 1
                  const XMAX_M = xSign * 0.12 * ROM_M
                  const M_MAG = Math.hypot(XMAX_M, ROM_M)
                  const THICK = 0.18 * M_MAG
                  const N_OPT = 80
                  const tauMax = techniqueMode === "j" ? Math.PI : 2 * Math.PI
                  const xs: number[] = []
                  const zs: number[] = []
                  for (let k = 0; k < N_OPT; k++) {
                    const tau = (k / (N_OPT - 1)) * tauMax
                    const along = (1 - Math.cos(tau)) / 2
                    const perp = Math.sin(tau) / 2
                    xs.push(along * XMAX_M + perp * THICK * (ROM_M / M_MAG) * xSign)
                    zs.push(-along * ROM_M + perp * THICK * (Math.abs(XMAX_M) / M_MAG))
                  }
                  optimal = { x: xs, z: zs }
                }

                // bounds in metres across visible reps + optimal, padded 8%
                let xMin = Infinity, xMax = -Infinity, zMin = Infinity, zMax = -Infinity
                for (const r of visible) {
                  for (const v of r.x_m) { if (v < xMin) xMin = v; if (v > xMax) xMax = v }
                  for (const v of r.z_m) { if (v < zMin) zMin = v; if (v > zMax) zMax = v }
                }
                if (optimal) {
                  for (const v of optimal.x) { if (v < xMin) xMin = v; if (v > xMax) xMax = v }
                  for (const v of optimal.z) { if (v < zMin) zMin = v; if (v > zMax) zMax = v }
                }
                const xRangeRaw = xMax - xMin || 0.02
                const zRangeRaw = zMax - zMin || 0.02
                const xPad = xRangeRaw * 0.08
                const zPad = zRangeRaw * 0.08
                xMin -= xPad; xMax += xPad
                zMin -= zPad; zMax += zPad

                const PAD_L = 44, PAD_R = 14, PAD_T = 16, PAD_B = 32
                const VW = 520, VH = 360
                const plotW = VW - PAD_L - PAD_R
                const plotH = VH - PAD_T - PAD_B
                const projX = (xm: number) =>
                  PAD_L + ((xm - xMin) / (xMax - xMin)) * plotW
                const projY = (zm: number) =>
                  PAD_T + ((zMax - zm) / (zMax - zMin)) * plotH
                const toPath = (xs: number[], zs: number[]) =>
                  xs
                    .map((xm, i) => `${i === 0 ? "M" : "L"} ${projX(xm).toFixed(1)},${projY(zs[i]).toFixed(1)}`)
                    .join(" ")

                // Arrow-head triangle at sample i, oriented along the
                // local path tangent (i → i+span). Returns the SVG
                // `points` attribute string.
                const arrowAt = (xs: number[], zs: number[], i: number, size = 7) => {
                  const span = Math.min(2, xs.length - 1 - i)
                  if (span <= 0 || i < 0) return ""
                  const x1 = projX(xs[i]), y1 = projY(zs[i])
                  const x2 = projX(xs[i + span]), y2 = projY(zs[i + span])
                  const dx = x2 - x1, dy = y2 - y1
                  const len = Math.hypot(dx, dy) || 1
                  const ux = dx / len, uy = dy / len
                  const tipX = x1 + ux * size * 0.7
                  const tipY = y1 + uy * size * 0.7
                  const halfBase = size * 0.55
                  const bX = x1 - ux * size * 0.5
                  const bY = y1 - uy * size * 0.5
                  const blX = bX - uy * halfBase, blY = bY + ux * halfBase
                  const brX = bX + uy * halfBase, brY = bY - ux * halfBase
                  return `${tipX.toFixed(1)},${tipY.toFixed(1)} ${blX.toFixed(1)},${blY.toFixed(1)} ${brX.toFixed(1)},${brY.toFixed(1)}`
                }

                // nice tick step: 1, 2, 5 × 10^k (in cm)
                const niceStepCm = (rangeCm: number, target = 5) => {
                  const rough = rangeCm / target
                  const exp = Math.floor(Math.log10(Math.max(rough, 1e-6)))
                  const f = rough / Math.pow(10, exp)
                  const nf = f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10
                  return nf * Math.pow(10, exp)
                }
                const xTickCm = niceStepCm((xMax - xMin) * 100)
                const zTickCm = niceStepCm((zMax - zMin) * 100)
                const xTicks: number[] = []
                for (
                  let v = Math.ceil((xMin * 100) / xTickCm) * xTickCm;
                  v <= xMax * 100 + 1e-6;
                  v += xTickCm
                ) xTicks.push(v)
                const zTicks: number[] = []
                for (
                  let v = Math.ceil((zMin * 100) / zTickCm) * zTickCm;
                  v <= zMax * 100 + 1e-6;
                  v += zTickCm
                ) zTicks.push(v)

                const fmtTick = (cm: number) =>
                  Math.abs(cm) < 0.05 ? "0" : (Number.isInteger(xTickCm) && Number.isInteger(zTickCm) ? cm.toFixed(0) : cm.toFixed(1))

                const sel =
                  selectedBarRep === "all"
                    ? bestNum
                      ? visible.find((r) => r.num === bestNum) ?? visible[0]
                      : visible[0]
                    : visible[0]

                const selArrows = sel
                  ? {
                      ecc: Math.max(0, Math.floor(sel.chest_idx / 2)),
                      conc: Math.floor((sel.chest_idx + sel.lockout_idx) / 2),
                    }
                  : null

                return (
                  <>
                    <g stroke="#161b23" strokeWidth="1">
                      {xTicks.map((cm) => (
                        <line key={`xg-${cm}`} x1={projX(cm / 100)} y1={PAD_T} x2={projX(cm / 100)} y2={PAD_T + plotH} />
                      ))}
                      {zTicks.map((cm) => (
                        <line key={`zg-${cm}`} x1={PAD_L} y1={projY(cm / 100)} x2={PAD_L + plotW} y2={projY(cm / 100)} />
                      ))}
                    </g>
                    {xMin < 0 && xMax > 0 && (
                      <line x1={projX(0)} y1={PAD_T} x2={projX(0)} y2={PAD_T + plotH} stroke="#2a323f" strokeDasharray="1 6" />
                    )}
                    {optimal && (
                      <>
                        <path
                          d={toPath(optimal.x, optimal.z)}
                          fill="none"
                          stroke="var(--hot)"
                          strokeWidth={1.6}
                          strokeDasharray="4 3"
                          opacity={0.9}
                        />
                        <g fill="var(--hot)" opacity={0.95}>
                          {techniqueMode === "j" ? (
                            <polygon
                              points={arrowAt(optimal.x, optimal.z, Math.floor(optimal.x.length * 0.5), 7)}
                            />
                          ) : (
                            <>
                              <polygon
                                points={arrowAt(optimal.x, optimal.z, Math.floor(optimal.x.length * 0.25), 7)}
                              />
                              <polygon
                                points={arrowAt(optimal.x, optimal.z, Math.floor(optimal.x.length * 0.75), 7)}
                              />
                            </>
                          )}
                        </g>
                      </>
                    )}
                    {selectedBarRep === "all" && (
                      <g fill="none" stroke="var(--bone)" strokeWidth={1.3} opacity={0.45}>
                        {visible
                          .filter((r) => !sel || r.num !== sel.num)
                          .map((r) => (
                            <path key={`bp-${r.num}`} d={toPath(r.x_m, r.z_m)} />
                          ))}
                      </g>
                    )}
                    {sel && (
                      <g fill="none" stroke="var(--sig)" strokeWidth={2.4}>
                        <path d={toPath(sel.x_m, sel.z_m)} />
                        <circle cx={projX(sel.x_m[0])} cy={projY(sel.z_m[0])} r={3} fill="var(--sig)" />
                        <circle
                          cx={projX(sel.x_m[sel.chest_idx])}
                          cy={projY(sel.z_m[sel.chest_idx])}
                          r={3}
                          fill="var(--sig)"
                        />
                      </g>
                    )}
                    {sel && selArrows && (
                      <g fill="var(--sig)">
                        <polygon points={arrowAt(sel.x_m, sel.z_m, selArrows.ecc, 8)} />
                        <polygon points={arrowAt(sel.x_m, sel.z_m, selArrows.conc, 8)} />
                      </g>
                    )}
                    <g fontFamily="JetBrains Mono, monospace" fontSize="10" fill="#5a6678" letterSpacing="1.4">
                      <text x="10" y="14">Z (cm)</text>
                      <text x={VW - 50} y={VH - 6}>X (cm)</text>
                      {zTicks.map((cm) => (
                        <text key={`zt-${cm}`} x={PAD_L - 6} y={projY(cm / 100) + 3} textAnchor="end">
                          {fmtTick(cm)}
                        </text>
                      ))}
                      {xTicks.map((cm) => (
                        <text key={`xt-${cm}`} x={projX(cm / 100)} y={PAD_T + plotH + 14} textAnchor="middle">
                          {fmtTick(cm)}
                        </text>
                      ))}
                    </g>
                  </>
                )
              })() : null}
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
            </svg>
          </div>
          <div className="barpath-foot">
            {(() => {
              const footRep =
                barPath && selectedBarRep !== "all"
                  ? barPath.reps.find((r) => r.num === selectedBarRep) ?? null
                  : barPath && bestNum
                  ? barPath.reps.find((r) => r.num === bestNum) ?? null
                  : null
              const propulsiveSrc =
                selectedBarRep !== "all"
                  ? reps.find((r) => r.num === selectedBarRep) ?? null
                  : bestRep
              const rom_m = footRep?.rom_m ?? propulsiveSrc?.rom_m ?? null
              return (
                <>
                  <div>
                    <div className="k">ROM</div>
                    <div className="v">
                      {rom_m != null ? (rom_m * 100).toFixed(1) : "—"} cm
                    </div>
                  </div>
                  <div>
                    <div className="k">Forward drift</div>
                    <div className="v">
                      {footRep?.peak_x_dev_m != null
                        ? `${(footRep.peak_x_dev_m * 100).toFixed(1)} cm`
                        : "—"}
                    </div>
                  </div>
                  <div>
                    <div className="k">Propulsive frac.</div>
                    <div className="v">
                      {propulsiveSrc?.propulsive_frac != null
                        ? `${(propulsiveSrc.propulsive_frac * 100).toFixed(0)}%`
                        : "—"}
                    </div>
                  </div>
                </>
              )
            })()}
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
