import { useEffect, useMemo, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { ArrowLeft, Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { LvpScatter } from "@/components/LvpScatter"
import { computeOneRm, listSessions, ApiError } from "@/api/client"
import type { Method, OneRmResponse, SessionInfo } from "@/api/types"
import { fmt } from "@/lib/format"

export default function OneRmPage() {
  const [searchParams] = useSearchParams()
  const initial = useMemo(() => new Set(searchParams.getAll("s")), [searchParams])

  const [sessions, setSessions] = useState<SessionInfo[]>([])
  const [selected, setSelected] = useState<Set<string>>(initial)
  const [method, setMethod] = useState<Method>("D")
  const [result, setResult] = useState<OneRmResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [computing, setComputing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    ;(async () => {
      setLoading(true)
      try {
        const list = await listSessions()
        setSessions(list)
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  useEffect(() => {
    if (initial.size >= 2 && sessions.length > 0) {
      void run(Array.from(initial), method)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions])

  async function run(ids: string[], m: Method) {
    setComputing(true)
    setError(null)
    try {
      const r = await computeOneRm({ session_ids: ids, method: m })
      setResult(r)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
      setResult(null)
    } finally {
      setComputing(false)
    }
  }

  function toggle(id: string) {
    setSelected((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const canRun = selected.size >= 2

  return (
    <div className="space-y-6">
      <div>
        <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
          <Link to="/">
            <ArrowLeft className="h-4 w-4" />
            Back to sessions
          </Link>
        </Button>
        <h1 className="text-2xl font-semibold tracking-tight">1RM consensus</h1>
        <p className="text-sm text-muted-foreground">
          Pick two or more sessions at different loads. Six estimators vote on the 1RM.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Sessions</CardTitle>
          <CardDescription>
            {selected.size} selected · same lifter required
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {loading ? (
            <Loader2 className="mx-auto my-4 h-5 w-5 animate-spin text-muted-foreground" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10" />
                  <TableHead>Filename</TableHead>
                  <TableHead>Lifter</TableHead>
                  <TableHead className="text-right">Load (lb)</TableHead>
                  <TableHead className="text-right">Reps</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sessions.map((s) => (
                  <TableRow key={s.session_id}>
                    <TableCell>
                      <Checkbox
                        checked={selected.has(s.session_id)}
                        onCheckedChange={() => toggle(s.session_id)}
                      />
                    </TableCell>
                    <TableCell className="font-medium">{s.filename}</TableCell>
                    <TableCell>{s.lifter ?? "—"}</TableCell>
                    <TableCell className="text-right">{s.load_lb ?? "—"}</TableCell>
                    <TableCell className="text-right">
                      {s.n_reps_prescribed ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          <div className="flex items-center gap-3">
            <Select value={method} onValueChange={(v) => setMethod(v as Method)}>
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="A">A</SelectItem>
                <SelectItem value="B">B</SelectItem>
                <SelectItem value="C">C</SelectItem>
                <SelectItem value="D">D (default)</SelectItem>
              </SelectContent>
            </Select>
            <Button
              disabled={!canRun || computing}
              onClick={() => run(Array.from(selected), method)}
            >
              {computing && <Loader2 className="h-4 w-4 animate-spin" />}
              Compute 1RM
            </Button>
          </div>
          {error && (
            <pre className="whitespace-pre-wrap rounded-md bg-destructive/10 p-3 text-xs text-destructive">
              {error}
            </pre>
          )}
        </CardContent>
      </Card>

      {result && (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-3xl">
                {result.consensus_one_rm_lb != null
                  ? `${result.consensus_one_rm_lb.toFixed(1)} lb`
                  : "—"}
              </CardTitle>
              <CardDescription>
                Consensus 1RM for lifter {result.lifter} · method {result.method_used}
                {result.ci95[0] != null && result.ci95[1] != null && (
                  <>
                    {" "}· 95% CI [{result.ci95[0]!.toFixed(1)},{" "}
                    {result.ci95[1]!.toFixed(1)}] lb
                  </>
                )}
              </CardDescription>
            </CardHeader>
            {result.notes && (
              <CardContent>
                <p className="text-sm text-muted-foreground">{result.notes}</p>
              </CardContent>
            )}
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Load–velocity profile</CardTitle>
              <CardDescription>
                Each dot is a session (best MPV vs load). Lines show linear fits from MPV and PCV estimators.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <LvpScatter sessions={result.sessions} estimators={result.estimators} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Estimators</CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Valid</TableHead>
                    <TableHead className="text-right">1RM (lb)</TableHead>
                    <TableHead className="text-right">slope</TableHead>
                    <TableHead className="text-right">intercept</TableHead>
                    <TableHead className="text-right">R²</TableHead>
                    <TableHead className="text-right">MVT</TableHead>
                    <TableHead>Notes</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {result.estimators.map((e) => (
                    <TableRow key={e.name}>
                      <TableCell className="font-medium">{e.name}</TableCell>
                      <TableCell>{e.valid ? "yes" : "no"}</TableCell>
                      <TableCell className="text-right">{fmt(e.one_rm_lb, 1)}</TableCell>
                      <TableCell className="text-right">{fmt(e.slope, 2)}</TableCell>
                      <TableCell className="text-right">{fmt(e.intercept, 2)}</TableCell>
                      <TableCell className="text-right">{fmt(e.r2, 3)}</TableCell>
                      <TableCell className="text-right">{fmt(e.mvt, 2)}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {e.notes || "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Session summary</CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead className="text-right">Load (lb)</TableHead>
                    <TableHead className="text-right">Reps</TableHead>
                    <TableHead className="text-right">Best MPV</TableHead>
                    <TableHead className="text-right">Best MCV</TableHead>
                    <TableHead className="text-right">Best PCV</TableHead>
                    <TableHead className="text-right">VL%</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {result.sessions.map((s) => (
                    <TableRow key={s.session_id}>
                      <TableCell className="font-medium">{s.name}</TableCell>
                      <TableCell className="text-right">{s.load_lb}</TableCell>
                      <TableCell className="text-right">
                        {s.n_reps_detected}/{s.n_reps_prescribed}
                      </TableCell>
                      <TableCell className="text-right">{fmt(s.best_mpv, 3)}</TableCell>
                      <TableCell className="text-right">{fmt(s.best_mcv, 3)}</TableCell>
                      <TableCell className="text-right">{fmt(s.best_pcv, 3)}</TableCell>
                      <TableCell className="text-right">
                        {s.vl_frac != null ? `${(s.vl_frac * 100).toFixed(1)}%` : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
