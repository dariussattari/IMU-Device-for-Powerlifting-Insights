import { useEffect, useMemo, useRef, useState } from "react"
import { ApiError, deleteSession, uploadSession } from "@/api/client"
import type { SessionInfo } from "@/api/types"
import { fmt, fmtInt } from "@/lib/format"

interface Props {
  sessions: SessionInfo[]
  loading: boolean
  selectedId: string | null
  onSelect: (id: string | null) => void
  onRefresh: () => void | Promise<void>
  onJumpToAnalysis: () => void
}

interface Pending {
  id: string
  csv: File
  annotations: File | null
  lifter: string
  load_lb: string
  n_reps_prescribed: string
}

const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

function makeId() {
  return Math.random().toString(36).slice(2)
}

function dayOf(iso: string): string {
  try {
    const d = new Date(iso)
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
  } catch {
    return iso
  }
}

function monthShort(iso: string): string {
  try {
    return MONTHS[new Date(iso).getMonth()] ?? "—"
  } catch {
    return "—"
  }
}

function dayNum(iso: string): string {
  try {
    return String(new Date(iso).getDate()).padStart(2, "0")
  } catch {
    return "—"
  }
}

function hhmm(iso: string): string {
  try {
    const d = new Date(iso)
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`
  } catch {
    return "—"
  }
}

interface DayGroup {
  dayKey: string           // unique key per session batch, e.g. 2026-04-22@18:36
  dateKey: string          // calendar date, e.g. 2026-04-22
  month: string            // APR
  num: string              // 22
  time: string             // 18:36 — time-of-day of the batch start
  lifters: Set<string>
  entries: SessionInfo[]
}

// Gap (in seconds) beyond which two adjacent uploads are treated as
// different sessions. Sequential uploads in one "+ New session" batch
// are seconds apart; real-world gym-time gaps between sessions are
// minutes-to-hours.
const BATCH_GAP_S = 120

/**
 * Group uploaded sessions into batches. Each "+ New session → Upload"
 * click becomes one card, even if several batches happen on the same
 * calendar day. Two sessions land in the same batch iff their
 * uploaded_at timestamps are within BATCH_GAP_S of each other.
 *
 * The backend already returns sessions sorted uploaded_at DESC, but
 * we sort ASC locally for the sliding-window pass, then flip the
 * output so the newest batch appears first.
 */
function groupByBatch(sessions: SessionInfo[]): DayGroup[] {
  if (sessions.length === 0) return []
  const asc = [...sessions].sort((a, b) =>
    a.uploaded_at < b.uploaded_at ? -1 : a.uploaded_at > b.uploaded_at ? 1 : 0
  )
  const batches: DayGroup[] = []
  let current: DayGroup | null = null
  let lastTs = -Infinity
  for (const s of asc) {
    const ts = new Date(s.uploaded_at).getTime()
    const gapS = (ts - lastTs) / 1000
    if (!current || gapS > BATCH_GAP_S) {
      current = {
        dayKey: `${dayOf(s.uploaded_at)}@${hhmm(s.uploaded_at)}`,
        dateKey: dayOf(s.uploaded_at),
        month: monthShort(s.uploaded_at),
        num: dayNum(s.uploaded_at),
        time: hhmm(s.uploaded_at),
        lifters: new Set(),
        entries: [],
      }
      batches.push(current)
    }
    if (s.lifter) current.lifters.add(s.lifter)
    current.entries.push(s)
    lastTs = ts
  }
  // newest batch first (matches the backend's DESC list order the user expects)
  return batches.reverse()
}

export default function SessionsTab({
  sessions,
  loading,
  selectedId,
  onSelect,
  onRefresh,
  onJumpToAnalysis,
}: Props) {
  const [mode, setMode] = useState<"view" | "upload">(sessions.length === 0 ? "upload" : "view")
  const [pending, setPending] = useState<Pending[]>([])
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedDay, setSelectedDay] = useState<string | null>(null)
  const [drag, setDrag] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const days = useMemo(() => groupByBatch(sessions), [sessions])

  // keep selectedDay in sync with selectedId, or default to first batch
  useEffect(() => {
    if (!days.length) {
      setSelectedDay(null)
      return
    }
    if (selectedId) {
      // find the batch that actually contains the selected session
      const hit = days.find((d) =>
        d.entries.some((e) => e.session_id === selectedId)
      )
      if (hit) {
        setSelectedDay(hit.dayKey)
        return
      }
    }
    setSelectedDay((cur) => (cur && days.some((d) => d.dayKey === cur) ? cur : days[0].dayKey))
  }, [days, sessions, selectedId])

  useEffect(() => {
    if (mode === "view" && !sessions.length) setMode("upload")
  }, [mode, sessions.length])

  const activeDay = days.find((d) => d.dayKey === selectedDay) ?? null

  // If multiple batches exist for a single calendar date, show the
  // batch time in labels so they can be told apart.
  const dateCounts = useMemo(() => {
    const m = new Map<string, number>()
    for (const d of days) m.set(d.dateKey, (m.get(d.dateKey) ?? 0) + 1)
    return m
  }, [days])

  function addFiles(files: File[]) {
    const csvs: Pending[] = files
      .filter((f) => f.name.toLowerCase().endsWith(".csv"))
      .map((f) => ({
        id: makeId(),
        csv: f,
        annotations: null,
        lifter: "",
        load_lb: "",
        n_reps_prescribed: "",
      }))
    setPending((p) => [...p, ...csvs])
  }

  function updatePending(id: string, patch: Partial<Pending>) {
    setPending((p) => p.map((r) => (r.id === id ? { ...r, ...patch } : r)))
  }

  // Lifter is a session-level field — typing it on any pending row
  // applies to every set in this batch. Load and target-reps remain
  // per-row because sets at different loads share the lifter.
  function setBatchLifter(lifter: string) {
    setPending((p) => p.map((r) => ({ ...r, lifter })))
  }

  function removePending(id: string) {
    setPending((p) => p.filter((r) => r.id !== id))
  }

  function attachAnnotations(id: string, f: File | null) {
    updatePending(id, { annotations: f })
  }

  async function uploadAll() {
    setUploading(true)
    setError(null)
    const failures: string[] = []
    for (const row of pending) {
      try {
        await uploadSession({
          csv: row.csv,
          annotations: row.annotations ?? undefined,
          lifter: row.lifter || undefined,
          load_lb: row.load_lb ? Number(row.load_lb) : undefined,
          n_reps_prescribed: row.n_reps_prescribed ? Number(row.n_reps_prescribed) : undefined,
        })
      } catch (e) {
        failures.push(`${row.csv.name}: ${e instanceof ApiError ? e.message : String(e)}`)
      }
    }
    setPending([])
    setUploading(false)
    if (failures.length) setError(failures.join("\n"))
    await onRefresh()
    if (!failures.length) setMode("view")
  }

  async function handleDelete(id: string) {
    try {
      await deleteSession(id)
      if (selectedId === id) onSelect(null)
      await onRefresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function handleDeleteBatch(batch: DayGroup) {
    const n = batch.entries.length
    const who = batch.entries[0]?.lifter
    const tag = who ? `${who} · ${batch.dateKey}` : batch.dateKey
    const confirmMsg = `Delete session (${tag}) and all ${n} ${n === 1 ? "set" : "sets"}?\nThis cannot be undone.`
    if (!window.confirm(confirmMsg)) return
    const failures: string[] = []
    for (const e of batch.entries) {
      try {
        await deleteSession(e.session_id)
      } catch (err) {
        failures.push(
          `${e.filename}: ${err instanceof ApiError ? err.message : String(err)}`
        )
      }
    }
    // if the currently selected set was inside this batch, clear selection
    if (batch.entries.some((e) => e.session_id === selectedId)) {
      onSelect(null)
    }
    if (failures.length) setError(failures.join("\n"))
    await onRefresh()
  }

  return (
    <section className="tabview">
      <div className="sess-head-row">
        <div>
          <h2>Sessions &amp; sets</h2>
          <div className="sub">
            {sessions.length} {sessions.length === 1 ? "set" : "sets"} logged · {days.length}{" "}
            {days.length === 1 ? "session" : "sessions"}
          </div>
        </div>
        <button
          className="btn"
          onClick={() => {
            setMode("upload")
            setPending([])
          }}
        >
          + New session
        </button>
      </div>

      <div className="sess-layout">
        {/* left · sessions list */}
        <div className="panel date-list">
          <div className="panel-h">
            <span className="tit">Sessions</span>
            <span className="r">
              <span className="chip">{days.length} total</span>
            </span>
          </div>
          {loading ? (
            <div className="loading">loading…</div>
          ) : days.length === 0 ? (
            <div className="empty">no uploads yet — drop a CSV to start</div>
          ) : (
            days.map((d) => {
              const isOn = d.dayKey === selectedDay && mode === "view"
              const label =
                d.entries[0]?.lifter
                  ? `${d.entries[0].lifter} · ${d.entries.length} ${
                      d.entries.length === 1 ? "set" : "sets"
                    }`
                  : `${d.entries.length} ${d.entries.length === 1 ? "set" : "sets"}`
              const first = d.entries[0]
              const needsTime = (dateCounts.get(d.dateKey) ?? 0) > 1
              return (
                <div
                  key={d.dayKey}
                  className={`date-row${isOn ? " on" : ""}`}
                  onClick={() => {
                    setSelectedDay(d.dayKey)
                    setMode("view")
                    if (first) onSelect(first.session_id)
                  }}
                >
                  <div className="d">
                    {d.month}
                    <span className="num">{d.num}</span>
                  </div>
                  <div className="body">
                    <div className="ttl">
                      {first?.lifter ? `Bench press · ${first.lifter}` : "Bench press"}
                      {needsTime && (
                        <span style={{ color: "var(--ink-600)", marginLeft: 8 }}>
                          @ {d.time}
                        </span>
                      )}
                    </div>
                    <div className="meta">
                      {d.dateKey}
                      {needsTime && ` · ${d.time}`} · {label}
                    </div>
                  </div>
                  <div className="ct">
                    <b>{d.entries.length}</b>{" "}
                    {d.entries.length === 1 ? "set" : "sets"}
                  </div>
                  <button
                    className="del-batch"
                    title={`Delete this session and all ${d.entries.length} ${d.entries.length === 1 ? "set" : "sets"}`}
                    aria-label="Delete session"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleDeleteBatch(d)
                    }}
                  >
                    ×
                  </button>
                </div>
              )
            })
          )}
        </div>

        {/* right · edit form or upload form */}
        {mode === "upload" ? (
          <div className="panel">
            <div className="panel-h">
              <span className="tit">New session · drop files</span>
              <span className="r">
                <span className="chip">CSV only</span>
              </span>
            </div>
            <div className="form-body">
              <div
                className={`dropzone${drag ? " drag" : ""}`}
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault()
                  setDrag(true)
                }}
                onDragLeave={() => setDrag(false)}
                onDrop={(e) => {
                  e.preventDefault()
                  setDrag(false)
                  const files = Array.from(e.dataTransfer.files)
                  addFiles(files)
                }}
              >
                <div className="big">Drop IMU CSVs here</div>
                <div>
                  or click to select · attach annotations per file below
                </div>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv"
                multiple
                style={{ display: "none" }}
                onChange={(e) => {
                  const files = Array.from(e.target.files ?? [])
                  addFiles(files)
                  e.target.value = ""
                }}
              />

              {pending.map((row) => (
                <div key={row.id} className="pending-row">
                  <div className="top">
                    <span className="fname">{row.csv.name}</span>
                    <button
                      className="btn ghost"
                      style={{ padding: "4px 10px" }}
                      onClick={() => removePending(row.id)}
                      disabled={uploading}
                    >
                      Remove
                    </button>
                  </div>
                  <div className="grid">
                    <div className="field">
                      <label>
                        Lifter{" "}
                        <span style={{ color: "var(--ink-600)" }}>
                          (applies to all sets)
                        </span>
                      </label>
                      <input
                        value={row.lifter}
                        onChange={(e) => setBatchLifter(e.target.value)}
                        placeholder="D"
                      />
                    </div>
                    <div className="field">
                      <label>Load · lb</label>
                      <input
                        type="number"
                        value={row.load_lb}
                        onChange={(e) => updatePending(row.id, { load_lb: e.target.value })}
                        placeholder="185"
                      />
                    </div>
                    <div className="field">
                      <label>
                        Target reps{" "}
                        <span style={{ color: "var(--ink-600)" }}>(optional)</span>
                      </label>
                      <input
                        type="number"
                        value={row.n_reps_prescribed}
                        onChange={(e) =>
                          updatePending(row.id, { n_reps_prescribed: e.target.value })
                        }
                        placeholder="—"
                      />
                    </div>
                    <div className="field">
                      <label>Annotations CSV</label>
                      <label
                        className="dropzone"
                        style={{ padding: "10px 12px", fontSize: 11 }}
                      >
                        {row.annotations ? row.annotations.name : "optional — click to attach"}
                        <input
                          type="file"
                          accept=".csv"
                          style={{ display: "none" }}
                          onChange={(e) =>
                            attachAnnotations(row.id, e.target.files?.[0] ?? null)
                          }
                        />
                      </label>
                    </div>
                  </div>
                </div>
              ))}

              {error && <div className="err">{error}</div>}
            </div>

            <div className="form-foot">
              {sessions.length > 0 && (
                <button
                  className="btn ghost"
                  onClick={() => {
                    setMode("view")
                    setPending([])
                    setError(null)
                  }}
                  disabled={uploading}
                >
                  Cancel
                </button>
              )}
              <button
                className="btn"
                disabled={uploading || !pending.length}
                onClick={uploadAll}
              >
                {uploading
                  ? "Uploading…"
                  : pending.length
                  ? `Upload ${pending.length} ${pending.length === 1 ? "file" : "files"}`
                  : "Upload"}
              </button>
            </div>
          </div>
        ) : activeDay ? (
          <div className="panel">
            <div className="panel-h">
              <span className="tit">
                Session · {activeDay.month} {activeDay.num}
                {(dateCounts.get(activeDay.dateKey) ?? 0) > 1 && (
                  <span style={{ color: "var(--ink-600)", marginLeft: 6 }}>
                    @ {activeDay.time}
                  </span>
                )}
              </span>
              <span className="r">
                <span className="chip live">
                  {activeDay.entries.length}{" "}
                  {activeDay.entries.length === 1 ? "set" : "sets"}
                </span>
              </span>
            </div>

            <div className="form-body">
              <div className="form-grid">
                <div className="field">
                  <label>Date</label>
                  <input
                    type="text"
                    readOnly
                    value={
                      (dateCounts.get(activeDay.dateKey) ?? 0) > 1
                        ? `${activeDay.dateKey} · ${activeDay.time}`
                        : activeDay.dateKey
                    }
                  />
                </div>
                <div className="field">
                  <label>Lifter</label>
                  <input
                    type="text"
                    readOnly
                    value={
                      activeDay.lifters.size
                        ? Array.from(activeDay.lifters).join(", ")
                        : "—"
                    }
                  />
                </div>
                <div className="field">
                  <label>Lift</label>
                  <input type="text" readOnly value="Bench press" />
                </div>
                <div className="field">
                  <label>Session total reps</label>
                  <input
                    type="text"
                    readOnly
                    value={String(
                      activeDay.entries.reduce(
                        (a, b) => a + (b.n_reps_prescribed ?? 0),
                        0
                      ) || "—"
                    )}
                  />
                </div>
              </div>

              <div style={{ marginTop: 22 }}>
                <div
                  style={{
                    display: "flex",
                    alignItems: "baseline",
                    justifyContent: "space-between",
                  }}
                >
                  <div
                    style={{
                      fontFamily: "var(--f-mono)",
                      fontSize: 11,
                      letterSpacing: ".2em",
                      textTransform: "uppercase",
                      color: "var(--ink-700)",
                    }}
                  >
                    Sets &nbsp;·&nbsp; this session
                  </div>
                  <div
                    style={{
                      fontFamily: "var(--f-mono)",
                      fontSize: 10,
                      color: "var(--ink-600)",
                      letterSpacing: ".08em",
                    }}
                  >
                    reps recorded by IMU · load entered at upload
                  </div>
                </div>
                <table className="set-table">
                  <thead>
                    <tr>
                      <th style={{ width: 38 }}>#</th>
                      <th>Load · lb</th>
                      <th>Target reps</th>
                      <th>Duration</th>
                      <th>f<sub>s</sub> · Hz</th>
                      <th>Annot.</th>
                      <th>IMU file</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeDay.entries.map((s, i) => {
                      const isSelected = s.session_id === selectedId
                      return (
                        <tr
                          key={s.session_id}
                          onClick={() => onSelect(s.session_id)}
                          style={{
                            cursor: "pointer",
                            background: isSelected ? "rgba(180,255,120,.04)" : undefined,
                          }}
                        >
                          <td className="n">
                            {String(i + 1).padStart(2, "0")}
                          </td>
                          <td>
                            <span className="load">{s.load_lb ?? "—"}</span>
                          </td>
                          <td>{s.n_reps_prescribed ?? "—"}</td>
                          <td>{fmt(s.duration_s, 1)} s</td>
                          <td>{fmt(s.fs_hz, 0)}</td>
                          <td>
                            {s.has_annotations ? (
                              <span style={{ color: "var(--sig)" }}>yes</span>
                            ) : (
                              "—"
                            )}
                          </td>
                          <td
                            title={s.filename}
                            style={{
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                              maxWidth: 200,
                              color: "var(--ink-700)",
                            }}
                          >
                            {s.filename}
                          </td>
                          <td className="x">
                            <button
                              title="remove"
                              onClick={(e) => {
                                e.stopPropagation()
                                handleDelete(s.session_id)
                              }}
                            >
                              ×
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                {selectedId && (
                  <div
                    style={{
                      marginTop: 14,
                      fontFamily: "var(--f-mono)",
                      fontSize: 10,
                      color: "var(--ink-600)",
                      letterSpacing: ".1em",
                    }}
                  >
                    selected · {fmtInt(
                      activeDay.entries.find((e) => e.session_id === selectedId)?.load_lb ?? null
                    )}{" "}
                    lb
                  </div>
                )}
              </div>

              {error && <div className="err">{error}</div>}
            </div>

            <div className="form-foot">
              <button
                className="btn ghost"
                onClick={() => {
                  setMode("upload")
                  setPending([])
                }}
              >
                + Add set
              </button>
              <button
                className="btn"
                disabled={!selectedId}
                onClick={onJumpToAnalysis}
              >
                Open in Analysis →
              </button>
            </div>
          </div>
        ) : (
          <div className="panel">
            <div className="panel-h">
              <span className="tit">No session selected</span>
            </div>
            <div className="empty">Upload a CSV to begin.</div>
          </div>
        )}
      </div>
    </section>
  )
}
