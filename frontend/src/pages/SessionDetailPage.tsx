import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { ArrowLeft, Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { VelocityPlot } from "@/components/VelocityPlot"
import { analyzeSession, listSessions, ApiError } from "@/api/client"
import type { AnalyzeResponse, Method, SessionInfo } from "@/api/types"
import { fmt } from "@/lib/format"

export default function SessionDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [method, setMethod] = useState<Method>("D")
  const [session, setSession] = useState<SessionInfo | null>(null)
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    let cancel = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const [sessions, a] = await Promise.all([
          listSessions(),
          analyzeSession(id, { method, include: ["velocity", "sticking"] }),
        ])
        if (cancel) return
        setSession(sessions.find((s) => s.session_id === id) ?? null)
        setAnalysis(a)
      } catch (e) {
        if (cancel) return
        setError(e instanceof ApiError ? e.message : String(e))
      } finally {
        if (!cancel) setLoading(false)
      }
    })()
    return () => {
      cancel = true
    }
  }, [id, method])

  if (loading) {
    return (
      <div className="flex justify-center py-16 text-muted-foreground">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    )
  }
  if (error) {
    return <p className="text-destructive">{error}</p>
  }
  if (!analysis) return null

  const reps = analysis.reps ?? []
  const sticking = analysis.sticking ?? []
  const stickingByNum = new Map(sticking.map((s) => [s.num, s]))

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
            <Link to="/">
              <ArrowLeft className="h-4 w-4" />
              Back to sessions
            </Link>
          </Button>
          <h1 className="text-2xl font-semibold tracking-tight">
            {session?.filename ?? id}
          </h1>
          <p className="text-sm text-muted-foreground">
            {session?.lifter ? `Lifter ${session.lifter} · ` : ""}
            {session?.load_lb ? `${session.load_lb} lb · ` : ""}
            {session ? `${fmt(session.duration_s, 1)} s at ${fmt(session.fs_hz, 1)} Hz` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">Method</span>
          <Select value={method} onValueChange={(v) => setMethod(v as Method)}>
            <SelectTrigger className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="A">A — baseline</SelectItem>
              <SelectItem value="B">B — per-rep detrend</SelectItem>
              <SelectItem value="C">C — ZUPT + detrend</SelectItem>
              <SelectItem value="D">D — hybrid (default)</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Vertical velocity</CardTitle>
          <CardDescription>
            Green lines mark chest position, red lines mark lockout. Orange
            dots mark detected sticking points.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <VelocityPlot
            plot={analysis.plot_data}
            boundaries={analysis.rep_boundaries}
            sticking={sticking}
          />
        </CardContent>
      </Card>

      <Tabs defaultValue="reps">
        <TabsList>
          <TabsTrigger value="reps">Rep metrics ({reps.length})</TabsTrigger>
          <TabsTrigger value="sticking">
            Sticking points ({sticking.filter((s) => s.has_sticking).length}/
            {sticking.length})
          </TabsTrigger>
        </TabsList>
        <TabsContent value="reps">
          <Card>
            <CardContent className="pt-6">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>#</TableHead>
                    <TableHead className="text-right">chest (s)</TableHead>
                    <TableHead className="text-right">top (s)</TableHead>
                    <TableHead className="text-right">dur (s)</TableHead>
                    <TableHead className="text-right">MCV (m/s)</TableHead>
                    <TableHead className="text-right">MPV (m/s)</TableHead>
                    <TableHead className="text-right">PCV (m/s)</TableHead>
                    <TableHead className="text-right">ROM (m)</TableHead>
                    <TableHead className="text-right">t-PV (s)</TableHead>
                    <TableHead className="text-right">prop. frac</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {reps.map((r) => {
                    const sp = stickingByNum.get(r.num)
                    return (
                      <TableRow
                        key={r.num}
                        className={sp?.has_sticking ? "bg-amber-50/60" : ""}
                      >
                        <TableCell className="font-medium">{r.num}</TableCell>
                        <TableCell className="text-right">{fmt(r.chest_s, 2)}</TableCell>
                        <TableCell className="text-right">{fmt(r.top_s, 2)}</TableCell>
                        <TableCell className="text-right">{fmt(r.duration_s, 2)}</TableCell>
                        <TableCell className="text-right">{fmt(r.mcv, 3)}</TableCell>
                        <TableCell className="text-right font-medium">{fmt(r.mpv, 3)}</TableCell>
                        <TableCell className="text-right">{fmt(r.pcv, 3)}</TableCell>
                        <TableCell className="text-right">{fmt(r.rom_m, 3)}</TableCell>
                        <TableCell className="text-right">{fmt(r.tpv_s, 2)}</TableCell>
                        <TableCell className="text-right">{fmt(r.propulsive_frac, 2)}</TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="sticking">
          <Card>
            <CardContent className="pt-6">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>#</TableHead>
                    <TableHead>has SP</TableHead>
                    <TableHead className="text-right">PCV</TableHead>
                    <TableHead className="text-right">SP time (s)</TableHead>
                    <TableHead className="text-right">SP v (m/s)</TableHead>
                    <TableHead className="text-right">SP frac</TableHead>
                    <TableHead className="text-right">depth</TableHead>
                    <TableHead className="text-right">rel depth</TableHead>
                    <TableHead className="text-right">post amp</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sticking.map((sp) => (
                    <TableRow
                      key={sp.num}
                      className={sp.has_sticking ? "bg-amber-50/60" : ""}
                    >
                      <TableCell className="font-medium">{sp.num}</TableCell>
                      <TableCell>{sp.has_sticking ? "yes" : "no"}</TableCell>
                      <TableCell className="text-right">{fmt(sp.pcv, 3)}</TableCell>
                      <TableCell className="text-right">{fmt(sp.sp_t, 2)}</TableCell>
                      <TableCell className="text-right">{fmt(sp.sp_v, 3)}</TableCell>
                      <TableCell className="text-right">{fmt(sp.sp_frac, 2)}</TableCell>
                      <TableCell className="text-right">{fmt(sp.sp_depth, 3)}</TableCell>
                      <TableCell className="text-right">{fmt(sp.sp_rel_depth, 2)}</TableCell>
                      <TableCell className="text-right">{fmt(sp.post_amp, 3)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
