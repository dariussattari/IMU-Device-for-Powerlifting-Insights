import { useEffect, useState, useCallback } from "react"
import { listSessions } from "@/api/client"
import type { SessionInfo } from "@/api/types"
import SessionsTab from "@/pages/SessionsTab"
import AnalysisTab from "@/pages/AnalysisTab"
import OneRmStickingTab from "@/pages/OneRmStickingTab"
import ResearchTab from "@/pages/ResearchTab"

type TabKey = "sessions" | "analysis" | "onerm" | "research"

const TAB_LABELS: { key: TabKey; n: string; label: string }[] = [
  { key: "sessions", n: "01", label: "Sessions & sets" },
  { key: "analysis", n: "02", label: "Analysis" },
  { key: "onerm", n: "03", label: "1RM & sticking" },
  { key: "research", n: "04", label: "Research hypotheses" },
]

/**
 * Barbell icon, side view. Steel plates on the left (bone color),
 * signal-lime "data-loaded" plate on the right with telemetry ticks —
 * a visual pun: one side is raw iron, the other is what the platform
 * turns it into (velocity / 1RM / sticking output).
 *
 * Size via the wrapping element's font-size or explicit width/height.
 * Passes aria-hidden — the adjacent wordmark carries the label.
 */
function BarbellMark({ className = "bb-logo" }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 180 48"
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      aria-hidden="true"
    >
      {/* Outer plate (45 lb silhouette) — left, bone */}
      <rect
        x="2"
        y="3"
        width="11"
        height="42"
        rx="1"
        fill="#0d1117"
        stroke="var(--bone)"
        strokeWidth="1.4"
      />
      {/* Inner plate (25 lb silhouette) — left, bone */}
      <rect
        x="17"
        y="11"
        width="7"
        height="26"
        rx="1"
        fill="#0d1117"
        stroke="var(--bone)"
        strokeWidth="1.1"
      />
      {/* Collar — left */}
      <rect x="26" y="20" width="3" height="8" fill="var(--bone)" />

      {/* Bar shaft */}
      <rect x="29" y="23" width="122" height="2" fill="var(--bone)" />

      {/* Knurled grip marks in the middle of the bar */}
      <g stroke="var(--bone)" strokeWidth="0.7" opacity="0.55">
        <line x1="70" y1="20" x2="70" y2="28" />
        <line x1="76" y1="20" x2="76" y2="28" />
        <line x1="82" y1="20" x2="82" y2="28" />
        <line x1="88" y1="20" x2="88" y2="28" />
        <line x1="94" y1="20" x2="94" y2="28" />
        <line x1="100" y1="20" x2="100" y2="28" />
        <line x1="106" y1="20" x2="106" y2="28" />
      </g>

      {/* Collar — right */}
      <rect x="151" y="20" width="3" height="8" fill="var(--sig)" />

      {/* Inner plate — right, lime */}
      <rect
        x="156"
        y="11"
        width="7"
        height="26"
        rx="1"
        fill="#0d1117"
        stroke="var(--sig)"
        strokeWidth="1.1"
      />
      {/* Outer plate — right, lime, "data-loaded" */}
      <rect
        x="167"
        y="3"
        width="11"
        height="42"
        rx="1"
        fill="#0d1117"
        stroke="var(--sig)"
        strokeWidth="1.4"
      />
      {/* Subtle fill glow on the loaded plate */}
      <rect
        x="169"
        y="13"
        width="7"
        height="22"
        fill="var(--sig)"
        opacity="0.16"
      />
      {/* Telemetry ticks on the outer loaded plate */}
      <g stroke="var(--sig)" strokeWidth="0.9">
        <line x1="169" y1="16" x2="176" y2="16" />
        <line x1="169" y1="20" x2="176" y2="20" />
        <line x1="169" y1="24" x2="176" y2="24" />
        <line x1="169" y1="28" x2="176" y2="28" />
        <line x1="169" y1="32" x2="176" y2="32" />
      </g>
    </svg>
  )
}

/**
 * Compact wordmark version — just the bar + two plates. Used inside
 * the mono topbar/footer where the full icon would be too busy.
 */
function BarbellGlyph({ className = "bb-glyph" }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 36 12"
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      aria-hidden="true"
    >
      <rect x="0" y="2" width="3" height="8" fill="var(--bone)" />
      <rect x="4" y="4" width="2" height="4" fill="var(--bone)" />
      <rect x="6" y="5" width="24" height="2" fill="var(--bone)" />
      <rect x="30" y="4" width="2" height="4" fill="var(--sig)" />
      <rect x="33" y="2" width="3" height="8" fill="var(--sig)" />
    </svg>
  )
}

export default function App() {
  const [tab, setTab] = useState<TabKey>(() => {
    try {
      const saved = localStorage.getItem("imu_tab") as TabKey | null
      if (saved && TAB_LABELS.some((t) => t.key === saved)) return saved
    } catch {
      // ignore storage errors
    }
    return "sessions"
  })
  const [sessions, setSessions] = useState<SessionInfo[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const list = await listSessions()
      setSessions(list)
      // if nothing selected yet, default to the most-recently uploaded
      setSelectedId((cur) => {
        if (cur && list.some((s) => s.session_id === cur)) return cur
        return list[0]?.session_id ?? null
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  function pickTab(k: TabKey) {
    setTab(k)
    try {
      localStorage.setItem("imu_tab", k)
    } catch {
      // ignore
    }
  }

  const nowIso = new Date().toLocaleString("en-US", {
    month: "short",
    day: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })

  return (
    <div className="shell">
      {/* top utility strip */}
      <div className="topbar">
        <div className="left">
          <span className="dot" />
          <BarbellGlyph />
          <span className="brandword">BARBELL · LAB</span>
        </div>
        <div className="right">
          {nowIso} &nbsp;·&nbsp; Op · <b>D. Sattari</b>
        </div>
      </div>

      {/* masthead */}
      <div className="masthead">
        <h1 className="brand-h1">
          <BarbellMark />
          <span className="brand-word">
            Barbell <span className="a">Lab</span>
          </span>
        </h1>
        <div className="sub">
          Open-source barbell-mounted IMU platform for rep counting, velocity profiling,
          sticking-point detection, and load-velocity 1RM prediction. Current scope: bench press.
          Squat, deadlift, and 2D bar-path reconstruction are in development.
        </div>
      </div>

      {/* tabs */}
      <div className="tabs" role="tablist">
        {TAB_LABELS.map((t) => (
          <button
            key={t.key}
            className={`tab${tab === t.key ? " on" : ""}`}
            onClick={() => pickTab(t.key)}
            role="tab"
            aria-selected={tab === t.key}
          >
            <span className="n">{t.n}</span> {t.label}
          </button>
        ))}
      </div>

      {/* tab views */}
      {error && <div className="err" style={{ marginTop: 20 }}>{error}</div>}

      {tab === "sessions" && (
        <SessionsTab
          sessions={sessions}
          loading={loading}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onRefresh={refresh}
          onJumpToAnalysis={() => pickTab("analysis")}
        />
      )}
      {tab === "analysis" && (
        <AnalysisTab
          sessions={sessions}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onJumpToSessions={() => pickTab("sessions")}
        />
      )}
      {tab === "onerm" && (
        <OneRmStickingTab
          sessions={sessions}
          selectedId={selectedId}
          onJumpToSessions={() => pickTab("sessions")}
        />
      )}
      {tab === "research" && <ResearchTab />}

      {/* footer */}
      <div className="footer">
        <span className="logo">
          <BarbellGlyph />
          BARBELL · LAB
        </span>
        <span>
          Sattari · Mahin &nbsp;·&nbsp; open dataset &nbsp;·&nbsp; bench (squat · deadlift WIP)
          &nbsp;·&nbsp; <span style={{ color: "var(--sig)" }}>●</span> build {new Date().getFullYear()}
        </span>
        <span>LSM6DSOX / ESP32-S3</span>
      </div>
    </div>
  )
}
