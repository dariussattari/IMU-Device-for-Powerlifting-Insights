import { useEffect, useMemo, useState } from "react"
import {
  analyzeSession,
  ApiError,
  computeOneRm,
} from "@/api/client"
import type {
  AnalyzeResponse,
  EstimatorOut,
  OneRmResponse,
  PlotData,
  SessionInfo,
  StickingPoint,
} from "@/api/types"
import { fmt } from "@/lib/format"

interface Props {
  sessions: SessionInfo[]
  selectedId: string | null
  onJumpToSessions: () => void
}

interface LvpPoint {
  load: number
  mpv: number
  label: string
  isSelected: boolean
}

function LvpChart({
  selectedId,
  estimators,
  consensusLb,
  sessionSummaries,
}: {
  selectedId: string | null
  estimators: EstimatorOut[]
  consensusLb: number | null
  sessionSummaries: OneRmResponse["sessions"] | undefined
}) {
  // Pick the MPV-LVP estimator for the regression line + fit points.
  // Prefer the trimmed version (the one that drives consensus in
  // src/one_rm/one_rm.py), then any MPV-LVP, then anything with "MPV"
  // in the name. Falls back to null → we plot only per-session points.
  const lvMpv =
    estimators.find((e) => e.name.includes("MPV-LVP (trimmed)") && e.valid) ??
    estimators.find((e) => e.name.includes("MPV-LVP") && e.valid) ??
    estimators.find((e) => e.name.includes("MPV-LVP")) ??
    null
  const points: LvpPoint[] = useMemo(() => {
    const pts: LvpPoint[] = []
    // prefer real estimator points from the 1RM response
    if (lvMpv && lvMpv.x_points.length === lvMpv.y_points.length && lvMpv.x_points.length > 0) {
      for (let i = 0; i < lvMpv.x_points.length; i++) {
        pts.push({
          load: lvMpv.x_points[i],
          mpv: lvMpv.y_points[i],
          label: String(Math.round(lvMpv.x_points[i])),
          isSelected: false,
        })
      }
      return pts
    }
    // fallback: use the per-session best_mpv returned by /api/one-rm
    if (sessionSummaries && sessionSummaries.length > 0) {
      for (const s of sessionSummaries) {
        if (s.load_lb == null || s.best_mpv == null) continue
        pts.push({
          load: s.load_lb,
          mpv: s.best_mpv,
          label: String(s.load_lb),
          isSelected: s.session_id === selectedId,
        })
      }
    }
    // if neither is available we render no points (the axes still draw)
    return pts
  }, [lvMpv, sessionSummaries, selectedId])

  const loads = points.map((p) => p.load).concat(consensusLb ? [consensusLb] : [])
  const minLoad = loads.length ? Math.min(...loads) * 0.9 : 100
  const maxLoad = loads.length ? Math.max(...loads) * 1.05 : 400
  const mpvs = points.map((p) => p.mpv)
  const maxMpv = mpvs.length ? Math.max(...mpvs) * 1.15 : 1.2
  const mvt = lvMpv?.mvt ?? 0.17

  // plot coords (viewBox 0..620 x 0..300; plot region x 60..600 y 30..270)
  const x = (load: number) => 60 + ((load - minLoad) / (maxLoad - minLoad)) * 540
  const y = (v: number) => 270 - (v / maxMpv) * 240

  const slope = lvMpv?.slope ?? null
  const intercept = lvMpv?.intercept ?? null
  const hasLine = slope != null && intercept != null
  const lineX1 = minLoad
  const lineY1 = hasLine ? slope! * lineX1 + intercept! : 0
  const lineX2 = maxLoad
  const lineY2 = hasLine ? slope! * lineX2 + intercept! : 0

  const loadTicks = useMemo(() => {
    const t = []
    const step = Math.ceil((maxLoad - minLoad) / 4 / 25) * 25
    for (let v = Math.ceil(minLoad / 25) * 25; v <= maxLoad; v += step) t.push(v)
    return t
  }, [minLoad, maxLoad])

  return (
    <div className="panel">
      <div className="panel-h">
        <span className="tit">Load – velocity regression</span>
        <span className="r">
          <span className="chip">n={points.length}</span>
          <span className="chip">r² {lvMpv?.r2 != null ? lvMpv.r2.toFixed(3) : "—"}</span>
        </span>
      </div>
      <div className="lv-chart">
        <svg viewBox="0 0 620 300" preserveAspectRatio="none">
          <g stroke="#1f2632" strokeWidth="1">
            <line x1="60" y1="30" x2="600" y2="30" />
            <line x1="60" y1="90" x2="600" y2="90" />
            <line x1="60" y1="150" x2="600" y2="150" />
            <line x1="60" y1="210" x2="600" y2="210" />
            <line x1="60" y1="270" x2="600" y2="270" />
            <line x1="60" y1="30" x2="60" y2="270" />
            <line x1="600" y1="30" x2="600" y2="270" />
          </g>
          <g fontFamily="JetBrains Mono, monospace" fontSize="10" fill="#5a6678" letterSpacing="1.4">
            <text x="8" y="34">{(maxMpv * 1).toFixed(1)}</text>
            <text x="8" y="94">{(maxMpv * 0.75).toFixed(2)}</text>
            <text x="8" y="154">{(maxMpv * 0.5).toFixed(2)}</text>
            <text x="8" y="214">{(maxMpv * 0.25).toFixed(2)}</text>
            <text x="8" y="274">0.0</text>
            <text x="8" y="16">MPV · m/s</text>
            {loadTicks.map((t) => (
              <text key={t} x={x(t) - 15} y="290">{t}</text>
            ))}
            <text x="555" y="300">Load · lb</text>
          </g>

          {/* regression line + CI band */}
          {hasLine && (
            <>
              <line x1={x(lineX1)} y1={y(lineY1)} x2={x(lineX2)} y2={y(lineY2)} stroke="var(--sig)" strokeWidth="2" />
              <polygon
                points={`${x(lineX1)},${y(lineY1) - 8} ${x(lineX2)},${y(lineY2) - 8} ${x(lineX2)},${y(lineY2) + 8} ${x(lineX1)},${y(lineY1) + 8}`}
                fill="var(--sig)"
                opacity=".08"
              />
            </>
          )}

          {/* MVT line */}
          <line x1="60" y1={y(mvt)} x2="600" y2={y(mvt)} stroke="var(--ink-600)" strokeDasharray="3 4" />
          <text x="566" y={y(mvt) - 4} fontFamily="JetBrains Mono, monospace" fontSize="10" fill="#8892a4">
            MVT {mvt.toFixed(2)}
          </text>

          {/* consensus 1RM vertical */}
          {consensusLb != null && (
            <>
              <line
                x1={x(consensusLb)}
                y1="30"
                x2={x(consensusLb)}
                y2="270"
                stroke="var(--sig)"
                strokeDasharray="3 4"
                opacity="0.8"
              />
              <text
                x={x(consensusLb) + 6}
                y="42"
                fontFamily="JetBrains Mono, monospace"
                fontSize="10"
                fill="oklch(0.88 0.18 125)"
              >
                1RM {consensusLb.toFixed(0)} lb
              </text>
            </>
          )}

          {/* data points */}
          <g>
            {points.map((p, i) => (
              <g key={`${p.load}-${i}`}>
                <circle
                  cx={x(p.load)}
                  cy={y(p.mpv)}
                  r={p.isSelected ? 8 : 5}
                  fill={p.isSelected ? "var(--sig)" : "var(--bone)"}
                  stroke={p.isSelected ? "var(--bone)" : "var(--sig)"}
                  strokeWidth="2"
                />
                {p.isSelected && (
                  <text
                    x={x(p.load) + 12}
                    y={y(p.mpv) - 6}
                    fontFamily="JetBrains Mono, monospace"
                    fontSize="10"
                    fill="var(--sig)"
                  >
                    ◀ {p.load} lb · {p.mpv.toFixed(2)}
                  </text>
                )}
              </g>
            ))}
          </g>
        </svg>
      </div>
    </div>
  )
}

/**
 * Build a real vy(t) SVG path for one rep, normalized to the
 * stick-viz coordinate system (viewBox 0..320 x 0..180).
 * Returns the stroke path + fill polygon + the x coord of the
 * detected sticking point so the overlay aligns with the real curve.
 */
function buildStickingCurve(
  plot: PlotData,
  chest_s: number,
  top_s: number,
  sp_t: number | null,
): { strokeD: string; fillD: string; spX: number | null } | null {
  const t = plot.t
  const vy = plot.vy
  if (!t.length || !vy.length || top_s <= chest_s) return null
  let i0 = 0
  while (i0 < t.length && t[i0] < chest_s) i0++
  let i1 = i0
  while (i1 < t.length && t[i1] <= top_s) i1++
  if (i1 - i0 < 4) return null
  const seg = vy.slice(i0, i1)
  const tseg = t.slice(i0, i1)
  const vMin = Math.min(...seg)
  const vMax = Math.max(...seg)
  const vRange = vMax - vMin || 1
  const tMin = tseg[0]
  const tMax = tseg[tseg.length - 1]
  const tRange = tMax - tMin || 1
  // viewBox: 0..320 wide, 0..180 tall; leave 10px top margin, 20px bottom
  const W = 320
  const Htop = 10
  const Hbot = 160 // vy draws inside 10..160 band
  const toX = (tt: number) => ((tt - tMin) / tRange) * W
  const toY = (vv: number) => Htop + (1 - (vv - vMin) / vRange) * (Hbot - Htop)
  // downsample to ≤80 plot points
  const stride = Math.max(1, Math.floor(seg.length / 80))
  const pts: [number, number][] = []
  for (let i = 0; i < seg.length; i += stride) {
    pts.push([toX(tseg[i]), toY(seg[i])])
  }
  // ensure last point is included
  const last = seg.length - 1
  if (pts[pts.length - 1]?.[0] !== toX(tseg[last])) {
    pts.push([toX(tseg[last]), toY(seg[last])])
  }
  const strokeD =
    "M" + pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" L")
  const fillD =
    strokeD +
    ` L${pts[pts.length - 1][0].toFixed(1)},180 L${pts[0][0].toFixed(1)},180 Z`
  const spX =
    sp_t != null && sp_t >= tMin && sp_t <= tMax ? toX(sp_t) : null
  return { strokeD, fillD, spX }
}

function StickingPanel({
  analysis,
  loading,
  sourceLabel,
}: {
  analysis: AnalyzeResponse | null
  loading: boolean
  sourceLabel?: string | null
}) {
  const stickingResult: StickingPoint[] = analysis?.sticking ?? []
  const flagged = stickingResult.filter((s) => s.has_sticking)
  const meanFrac = flagged.length
    ? flagged.reduce((a, b) => a + (b.sp_frac ?? 0), 0) / flagged.length
    : null

  const phase: "bottom" | "middle" | "top" =
    meanFrac == null ? "middle" : meanFrac < 0.33 ? "bottom" : meanFrac < 0.66 ? "middle" : "top"

  // Pick the rep to draw. Prefer the deepest flagged sticking rep so the
  // valley is visible; fall back to the first rep so the panel still
  // shows a real vy curve even on clean sets.
  const repToDraw: StickingPoint | null = useMemo(() => {
    if (flagged.length > 0) {
      return flagged.reduce((best, s) =>
        s.sp_depth > (best?.sp_depth ?? -Infinity) ? s : best,
        flagged[0],
      )
    }
    return stickingResult[0] ?? null
  }, [flagged, stickingResult])

  const curve = useMemo(() => {
    if (!analysis || !repToDraw) return null
    return buildStickingCurve(
      analysis.plot_data,
      repToDraw.chest_s,
      repToDraw.top_s,
      repToDraw.sp_t,
    )
  }, [analysis, repToDraw])

  return (
    <div className="panel">
      <div className="panel-h">
        <span className="tit">Sticking region</span>
        <span className="r">
          {sourceLabel && <span className="chip">{sourceLabel}</span>}
          {flagged.length > 0 ? (
            <span className="chip warn">detected ×{flagged.length}</span>
          ) : (
            <span className="chip">clean</span>
          )}
        </span>
      </div>

      <div className="stick-anchor">
        <div className={`anc${phase === "bottom" ? " on" : ""}`}>
          <div className="k">Bottom</div>
          <div className="v">0 – 33%</div>
        </div>
        <div className={`anc${phase === "middle" ? " on" : ""}`}>
          <div className="k">
            {phase === "middle" ? "Middle · anchor" : "Middle"}
          </div>
          <div className="v">33 – 66%</div>
        </div>
        <div className={`anc${phase === "top" ? " on" : ""}`}>
          <div className="k">Top</div>
          <div className="v">66 – 100%</div>
        </div>
      </div>

      <div className="stick-viz">
        <svg viewBox="0 0 320 180" preserveAspectRatio="none">
          <defs>
            <linearGradient id="stkFill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="oklch(0.88 0.18 125)" stopOpacity=".3" />
              <stop offset="1" stopColor="oklch(0.88 0.18 125)" stopOpacity="0" />
            </linearGradient>
          </defs>
          {/* phase bands */}
          <rect x="0" y="0" width="106" height="180" fill="rgba(90,102,120,.05)" />
          <rect x="213" y="0" width="107" height="180" fill="rgba(90,102,120,.05)" />

          {/* Real vy(t) curve for the selected rep (deepest sticking if any,
              else first rep). Built from analysis.plot_data.vy sliced
              between chest_s and top_s. */}
          {curve ? (
            <>
              <path d={curve.fillD} fill="url(#stkFill)" />
              <path
                d={curve.strokeD}
                fill="none"
                stroke="var(--sig)"
                strokeWidth="1.8"
              />
              {/* Real sticking marker at the detected sp_t of the drawn rep */}
              {curve.spX != null && (
                <>
                  <line
                    x1={curve.spX}
                    y1="0"
                    x2={curve.spX}
                    y2="180"
                    stroke="var(--hot)"
                    strokeDasharray="2 3"
                    opacity="0.7"
                  />
                  <text
                    x={curve.spX - 14}
                    y="20"
                    fontFamily="JetBrains Mono, monospace"
                    fontSize="10"
                    fill="oklch(0.78 0.18 55)"
                    letterSpacing="1.4"
                  >
                    STICK
                  </text>
                </>
              )}
            </>
          ) : (
            <g
              transform="translate(160 90)"
              fontFamily="JetBrains Mono, monospace"
            >
              <text
                x="0"
                y="0"
                textAnchor="middle"
                fontSize="10"
                fill="var(--ink-600)"
                letterSpacing="1.2"
              >
                {loading ? "analyzing…" : "select a session to view vy(t)"}
              </text>
            </g>
          )}

          <g fontFamily="JetBrains Mono, monospace" fontSize="9" fill="#5a6678" letterSpacing="1.4">
            <text x="6" y="172" fill={phase === "bottom" ? "var(--hot)" : undefined}>BOTTOM</text>
            <text x="130" y="172" fill={phase === "middle" ? "var(--hot)" : undefined}>MIDDLE</text>
            <text x="270" y="172" fill={phase === "top" ? "var(--hot)" : undefined}>TOP</text>
            <text x="2" y="12">Vy</text>
            <text x="295" y="12">t · concentric</text>
          </g>
        </svg>
        {repToDraw && (
          <div
            style={{
              fontFamily: "var(--f-mono)",
              fontSize: 10,
              color: "var(--ink-600)",
              letterSpacing: ".1em",
              marginTop: 6,
              textAlign: "center",
            }}
          >
            showing rep {repToDraw.num} ·{" "}
            {repToDraw.has_sticking
              ? `sp @ ${(repToDraw.sp_frac! * 100).toFixed(0)}% · Δv ${((repToDraw.sp_rel_depth ?? 0) * 100).toFixed(0)}%`
              : "no sticking detected"}
          </div>
        )}
      </div>

      <div className="stick-list">
        {loading ? (
          <div className="loading">analyzing…</div>
        ) : stickingResult.length === 0 ? (
          <div className="empty">no sticking analysis available</div>
        ) : (
          <>
            {stickingResult.map((s) => {
              if (!s.has_sticking) return null
              const frac = s.sp_frac ?? 0
              const phaseLbl =
                frac < 0.33 ? "bottom" : frac < 0.66 ? "middle" : "top"
              const depthPct = s.sp_rel_depth ? (s.sp_rel_depth * 100).toFixed(0) : "—"
              return (
                <div key={s.num} className="stick-row">
                  <span className="n">R{s.num}</span>
                  <span className="t">
                    {phaseLbl} · {(frac * 100).toFixed(0)}%
                  </span>
                  <span className="pct">Δv −{depthPct}%</span>
                </div>
              )
            })}
            {flagged.length > 0 && (
              <div className="stick-row" style={{ background: "rgba(180,255,120,.04)" }}>
                <span className="n">Σ</span>
                <span className="t">
                  anchored to <b style={{ color: "var(--hot)" }}>{phase}</b> (~
                  {meanFrac != null ? (meanFrac * 100).toFixed(0) : "—"}%)
                </span>
                <span className="pct" style={{ color: "var(--sig)" }}>consistent</span>
              </div>
            )}
            {flagged.length === 0 && stickingResult.length > 0 && (
              <div className="stick-row">
                <span className="n">Σ</span>
                <span className="t">no reps flagged in this set</span>
                <span className="pct" style={{ color: "var(--sig)" }}>clean</span>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default function OneRmStickingTab({ sessions, selectedId, onJumpToSessions }: Props) {
  // pick sessions belonging to the same lifter as selected, default all
  const [picked, setPicked] = useState<Set<string>>(() => new Set())
  const [oneRm, setOneRm] = useState<OneRmResponse | null>(null)
  // Sticking analyses are cached per session_id so flipping chips doesn't
  // refetch sets we've already analyzed.
  const [stickingCache, setStickingCache] = useState<Map<string, AnalyzeResponse>>(
    () => new Map()
  )
  const [loading, setLoading] = useState(false)
  const [loadingStick, setLoadingStick] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const lifters = useMemo(() => {
    const ls = new Set<string>()
    for (const s of sessions) if (s.lifter) ls.add(s.lifter)
    return Array.from(ls)
  }, [sessions])
  const [lifter, setLifter] = useState<string>(lifters[0] ?? "")

  useEffect(() => {
    if (!lifter && lifters.length) setLifter(lifters[0])
  }, [lifters, lifter])

  const lifterSessions = useMemo(() => {
    if (!lifter) return sessions
    return sessions.filter((s) => s.lifter === lifter)
  }, [sessions, lifter])

  // auto-pick all lifter sessions with load_lb set
  useEffect(() => {
    const next = new Set<string>()
    for (const s of lifterSessions) {
      if (s.load_lb != null) next.add(s.session_id)
    }
    setPicked(next)
  }, [lifterSessions])

  // ≥2 picked → linear LVP. =1 picked → fall back to single-session
  // estimators (González-Badillo population eq + within-set velocity-loss);
  // both are computed by the backend regardless of session count.
  const canRun = picked.size >= 1
  const singleSession = picked.size === 1

  useEffect(() => {
    let cancelled = false
    async function run() {
      if (!canRun) {
        setOneRm(null)
        return
      }
      setLoading(true)
      setError(null)
      try {
        const res = await computeOneRm({
          session_ids: Array.from(picked),
          method: "D",
        })
        if (!cancelled) setOneRm(res)
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
  }, [picked, canRun])

  // Fetch sticking analyses for every picked set (only the ones not in the
  // cache yet). The chosen analysis is then derived from the cache + picked
  // set in the memo below.
  useEffect(() => {
    const ids = Array.from(picked)
    const missing = ids.filter((id) => !stickingCache.has(id))
    if (missing.length === 0) {
      setLoadingStick(false)
      return
    }
    let cancelled = false
    setLoadingStick(true)
    Promise.all(
      missing.map((id) =>
        analyzeSession(id, { method: "D", include: ["sticking"] }).catch(
          () => null
        )
      )
    ).then((results) => {
      if (cancelled) return
      setStickingCache((prev) => {
        const next = new Map(prev)
        missing.forEach((id, i) => {
          const r = results[i]
          if (r) next.set(id, r)
        })
        return next
      })
      setLoadingStick(false)
    })
    return () => {
      cancelled = true
    }
  }, [picked, stickingCache])

  // Pick the analysis to render. With one set picked, just show that one.
  // With multiple, show the set with the deepest sticking point (greatest
  // sp_depth across flagged reps); fall back to the first picked when none
  // are flagged.
  const stickingAnalysis = useMemo<AnalyzeResponse | null>(() => {
    const candidates = Array.from(picked)
      .map((id) => stickingCache.get(id))
      .filter((a): a is AnalyzeResponse => a != null)
    if (candidates.length === 0) return null
    if (candidates.length === 1) return candidates[0]
    let best = candidates[0]
    let bestDepth = -Infinity
    for (const a of candidates) {
      const flagged = (a.sticking ?? []).filter((s) => s.has_sticking)
      if (flagged.length === 0) continue
      const d = Math.max(...flagged.map((f) => f.sp_depth))
      if (d > bestDepth) {
        bestDepth = d
        best = a
      }
    }
    return best
  }, [picked, stickingCache])

  const stickingSourceLabel = useMemo(() => {
    if (!stickingAnalysis) return null
    const src = sessions.find(
      (s) => s.session_id === stickingAnalysis.session_id
    )
    if (!src) return null
    const loadLbl = src.load_lb != null ? `${src.load_lb} lb` : "—"
    return picked.size > 1 ? `${loadLbl} · most prominent` : loadLbl
  }, [stickingAnalysis, sessions, picked])

  if (sessions.length < 1) {
    return (
      <section className="tabview">
        <div className="panel" style={{ padding: "48px 40px" }}>
          <div className="empty">
            Upload at least one session to project a 1RM.
          </div>
          <div style={{ textAlign: "center", marginTop: 16 }}>
            <button className="btn" onClick={onJumpToSessions}>
              Upload session
            </button>
          </div>
        </div>
      </section>
    )
  }

  const consensusLb = oneRm?.consensus_one_rm_lb ?? null
  const ci = oneRm?.ci95 ?? [null, null]
  const methodUsed = oneRm?.method_used ?? "D"
  const kg = consensusLb != null ? (consensusLb * 0.453592).toFixed(1) : null
  const lvMpv =
    oneRm?.estimators.find((e) => e.name.includes("MPV-LVP (trimmed)") && e.valid) ??
    oneRm?.estimators.find((e) => e.name.includes("MPV-LVP") && e.valid) ??
    oneRm?.estimators.find((e) => e.name.includes("MPV-LVP"))
  const r2 = lvMpv?.r2 ?? null
  const mvt = lvMpv?.mvt ?? null

  return (
    <section className="tabview">
      {/* lifter picker + session selection */}
      {lifters.length > 0 && (
        <div
          style={{
            display: "flex",
            gap: 16,
            alignItems: "center",
            marginBottom: 18,
            flexWrap: "wrap",
          }}
        >
          <div
            style={{
              fontFamily: "var(--f-mono)",
              fontSize: 11,
              letterSpacing: ".18em",
              textTransform: "uppercase",
              color: "var(--ink-700)",
            }}
          >
            Lifter
          </div>
          <div style={{ display: "flex", gap: 0, border: "1px solid var(--ink-400)" }}>
            {lifters.map((l) => (
              <button
                key={l}
                className="chip"
                style={{
                  border: "none",
                  borderRight: "1px solid var(--ink-400)",
                  padding: "6px 14px",
                  background: lifter === l ? "var(--sig)" : "transparent",
                  color: lifter === l ? "#06140a" : "var(--ink-800)",
                  fontWeight: lifter === l ? 700 : 400,
                  cursor: "pointer",
                }}
                onClick={() => setLifter(l)}
              >
                {l}
              </button>
            ))}
          </div>
          <div
            style={{
              marginLeft: "auto",
              fontFamily: "var(--f-mono)",
              fontSize: 10,
              color: "var(--ink-600)",
              letterSpacing: ".1em",
            }}
          >
            {picked.size} of {lifterSessions.length} sets included
            {!canRun && " · select a set to run"}
            {singleSession && " · single-set fallback (pop+VL)"}
          </div>
        </div>
      )}

      {error && <div className="err">{error}</div>}

      <div className="row-3">
        <LvpChart
          selectedId={selectedId}
          estimators={oneRm?.estimators ?? []}
          consensusLb={consensusLb}
          sessionSummaries={oneRm?.sessions}
        />

        <div className="panel one-rm">
          <div className="panel-h">
            <span className="tit">1RM · consensus</span>
            <span className="r">
              {loading ? (
                <span className="chip">computing…</span>
              ) : consensusLb != null ? (
                <span className="chip live">valid</span>
              ) : (
                <span className="chip">pending</span>
              )}
            </span>
          </div>
          <div className="herobox">
            <div className="label">Projected one-rep max</div>
            <div className="big">
              {consensusLb != null ? consensusLb.toFixed(0) : "—"}
              <span className="u">lb{kg && ` · ${kg} kg`}</span>
            </div>
            <div className="ci">
              95% CI <b>{fmt(ci[0], 0)} – {fmt(ci[1], 0)} lb</b>
              {oneRm?.notes && ` · ${oneRm.notes}`}
            </div>
            <div className="ci" style={{ marginTop: 4 }}>
              Method <b>{methodUsed}</b>
              {mvt != null && <> · MVT <b>{mvt.toFixed(2)} m/s</b></>}
              {r2 != null && <> · r² <b>{r2.toFixed(3)}</b></>}
            </div>
          </div>
          <div className="estimators">
            {oneRm?.estimators.length ? (
              oneRm.estimators.map((e) => (
                <div key={e.name} className={`est-row${e.valid ? "" : " dim"}`}>
                  <span className="name">{e.name}</span>
                  <span className="val">
                    {e.one_rm_lb != null ? `${e.one_rm_lb.toFixed(0)} lb` : "—"}
                  </span>
                  <span className="r2">
                    {e.r2 != null ? `r² .${String(Math.round(e.r2 * 1000)).padStart(3, "0")}` : e.notes || "heuristic"}
                  </span>
                </div>
              ))
            ) : (
              <div className="loading">{loading ? "computing…" : "select a set"}</div>
            )}
          </div>
        </div>

        <StickingPanel
          analysis={stickingAnalysis}
          loading={loadingStick}
          sourceLabel={stickingSourceLabel}
        />
      </div>

      {/* session selector */}
      <div style={{ marginTop: 24 }}>
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
          Sets included in regression
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {lifterSessions.map((s) => {
            const on = picked.has(s.session_id)
            return (
              <button
                key={s.session_id}
                className={`chip${on ? " live" : ""}`}
                style={{
                  cursor: "pointer",
                  background: on ? undefined : "transparent",
                }}
                onClick={() =>
                  setPicked((p) => {
                    const n = new Set(p)
                    if (n.has(s.session_id)) n.delete(s.session_id)
                    else n.add(s.session_id)
                    return n
                  })
                }
              >
                {s.load_lb ?? "—"} lb · {s.filename.slice(0, 22)}
              </button>
            )
          })}
        </div>
      </div>
    </section>
  )
}
