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
          <span className="brandword">IMU · LAB</span>
        </div>
        <div className="right">
          {nowIso} &nbsp;·&nbsp; Op · <b>D. Sattari</b>
        </div>
      </div>

      {/* masthead */}
      <div className="masthead">
        <h1>
          IMU <span className="a">Lab</span>
        </h1>
        <div className="sub">
          Open-source barbell-mounted IMU platform for rep counting, 3D bar-path reconstruction,
          velocity profiling, and 1RM prediction across the squat, bench press, and deadlift.
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
        <span className="logo">IMU · LAB</span>
        <span>
          Sattari · Mahin &nbsp;·&nbsp; open dataset &nbsp;·&nbsp; squat · bench · deadlift
          &nbsp;·&nbsp; <span style={{ color: "var(--sig)" }}>●</span> build {new Date().getFullYear()}
        </span>
        <span>LSM6DSOX / ESP32-S3 / EKF</span>
      </div>
    </div>
  )
}
