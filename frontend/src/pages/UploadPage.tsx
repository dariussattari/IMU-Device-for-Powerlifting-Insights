import { useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { Loader2, Paperclip, Trash2, X } from "lucide-react"

import { FileDropzone } from "@/components/FileDropzone"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  deleteSession,
  listSessions,
  uploadSession,
  ApiError,
} from "@/api/client"
import type { SessionInfo } from "@/api/types"
import { fmt, fmtDate } from "@/lib/format"

interface Pending {
  id: string
  csv: File
  annotations: File | null
  lifter: string
  load_lb: string
  n_reps_prescribed: string
}

function makeId() {
  return Math.random().toString(36).slice(2)
}

export default function UploadPage() {
  const navigate = useNavigate()
  const [pending, setPending] = useState<Pending[]>([])
  const [sessions, setSessions] = useState<SessionInfo[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function refresh() {
    setLoading(true)
    try {
      const list = await listSessions()
      setSessions(list)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  function addPending(files: File[]) {
    const rows: Pending[] = files
      .filter((f) => f.name.toLowerCase().endsWith(".csv"))
      .map((f) => ({
        id: makeId(),
        csv: f,
        annotations: null,
        lifter: "",
        load_lb: "",
        n_reps_prescribed: "",
      }))
    setPending((p) => [...p, ...rows])
  }

  function attachAnnotations(id: string, ann: File | null) {
    setPending((p) => p.map((r) => (r.id === id ? { ...r, annotations: ann } : r)))
  }

  function updatePending(id: string, patch: Partial<Pending>) {
    setPending((p) => p.map((r) => (r.id === id ? { ...r, ...patch } : r)))
  }

  function removePending(id: string) {
    setPending((p) => p.filter((r) => r.id !== id))
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
          n_reps_prescribed: row.n_reps_prescribed
            ? Number(row.n_reps_prescribed)
            : undefined,
        })
      } catch (e) {
        failures.push(
          `${row.csv.name}: ${e instanceof ApiError ? e.message : String(e)}`
        )
      }
    }
    setPending([])
    setUploading(false)
    if (failures.length) setError(failures.join("\n"))
    await refresh()
  }

  async function handleDelete(session_id: string) {
    try {
      await deleteSession(session_id)
      setSelected((s) => {
        const next = new Set(s)
        next.delete(session_id)
        return next
      })
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  function toggleSelected(id: string) {
    setSelected((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const selectedCount = selected.size
  const canRunOneRm = selectedCount >= 2

  return (
    <div className="space-y-8">
      <Card>
        <CardHeader>
          <CardTitle>Upload sessions</CardTitle>
          <CardDescription>
            Drag-drop one or more bench press CSV files. Add an annotations
            CSV per file if you have it; otherwise the detector will find reps
            automatically. Enter load and lifter for 1RM analysis.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <FileDropzone onFiles={addPending} />
          {pending.length > 0 && (
            <div className="space-y-3">
              {pending.map((row) => (
                <PendingRow
                  key={row.id}
                  row={row}
                  onAttach={(f) => attachAnnotations(row.id, f)}
                  onChange={(patch) => updatePending(row.id, patch)}
                  onRemove={() => removePending(row.id)}
                />
              ))}
              <div className="flex justify-end gap-2">
                <Button
                  variant="outline"
                  onClick={() => setPending([])}
                  disabled={uploading}
                >
                  Clear
                </Button>
                <Button onClick={uploadAll} disabled={uploading}>
                  {uploading && <Loader2 className="h-4 w-4 animate-spin" />}
                  Upload {pending.length} {pending.length === 1 ? "file" : "files"}
                </Button>
              </div>
            </div>
          )}
          {error && (
            <pre className="whitespace-pre-wrap rounded-md bg-destructive/10 p-3 text-xs text-destructive">
              {error}
            </pre>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>Sessions</CardTitle>
            <CardDescription>
              {sessions.length} uploaded. Select two or more to compute a 1RM.
            </CardDescription>
          </div>
          <Button
            disabled={!canRunOneRm}
            onClick={() => {
              const params = new URLSearchParams()
              for (const id of selected) params.append("s", id)
              navigate(`/one-rm?${params.toString()}`)
            }}
          >
            Run 1RM ({selectedCount})
          </Button>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex justify-center py-8 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : sessions.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No sessions yet.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10" />
                  <TableHead>Filename</TableHead>
                  <TableHead>Lifter</TableHead>
                  <TableHead className="text-right">Load (lb)</TableHead>
                  <TableHead className="text-right">Duration (s)</TableHead>
                  <TableHead className="text-right">Rate (Hz)</TableHead>
                  <TableHead>Annotations</TableHead>
                  <TableHead>Uploaded</TableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {sessions.map((s) => (
                  <TableRow key={s.session_id}>
                    <TableCell>
                      <Checkbox
                        checked={selected.has(s.session_id)}
                        onCheckedChange={() => toggleSelected(s.session_id)}
                      />
                    </TableCell>
                    <TableCell>
                      <Link
                        to={`/sessions/${s.session_id}`}
                        className="font-medium hover:underline"
                      >
                        {s.filename}
                      </Link>
                    </TableCell>
                    <TableCell>{s.lifter ?? "—"}</TableCell>
                    <TableCell className="text-right">
                      {s.load_lb ?? "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      {fmt(s.duration_s, 1)}
                    </TableCell>
                    <TableCell className="text-right">
                      {fmt(s.fs_hz, 1)}
                    </TableCell>
                    <TableCell>
                      {s.has_annotations ? "yes" : "no"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {fmtDate(s.uploaded_at)}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleDelete(s.session_id)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

interface PendingRowProps {
  row: Pending
  onAttach: (f: File | null) => void
  onChange: (patch: Partial<Pending>) => void
  onRemove: () => void
}

function PendingRow({ row, onAttach, onChange, onRemove }: PendingRowProps) {
  return (
    <div className="rounded-lg border p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="truncate font-mono text-sm">{row.csv.name}</div>
        <Button variant="ghost" size="icon" onClick={onRemove}>
          <X className="h-4 w-4" />
        </Button>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        <div>
          <Label htmlFor={`lifter-${row.id}`}>Lifter</Label>
          <Input
            id={`lifter-${row.id}`}
            value={row.lifter}
            onChange={(e) => onChange({ lifter: e.target.value })}
            placeholder="D"
          />
        </div>
        <div>
          <Label htmlFor={`load-${row.id}`}>Load (lb)</Label>
          <Input
            id={`load-${row.id}`}
            type="number"
            value={row.load_lb}
            onChange={(e) => onChange({ load_lb: e.target.value })}
            placeholder="185"
          />
        </div>
        <div>
          <Label htmlFor={`reps-${row.id}`}>Reps prescribed</Label>
          <Input
            id={`reps-${row.id}`}
            type="number"
            value={row.n_reps_prescribed}
            onChange={(e) => onChange({ n_reps_prescribed: e.target.value })}
            placeholder="3"
          />
        </div>
        <div>
          <Label>Annotations</Label>
          <label className="flex h-9 w-full cursor-pointer items-center gap-2 rounded-md border bg-transparent px-3 text-sm hover:bg-muted/50">
            <Paperclip className="h-4 w-4 text-muted-foreground" />
            <span className="truncate">
              {row.annotations ? row.annotations.name : "optional"}
            </span>
            <input
              type="file"
              accept=".csv"
              className="hidden"
              onChange={(e) => onAttach(e.target.files?.[0] ?? null)}
            />
          </label>
        </div>
      </div>
    </div>
  )
}
