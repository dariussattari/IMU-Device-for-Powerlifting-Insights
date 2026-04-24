import type {
  AnalyzeRequest,
  AnalyzeResponse,
  BarPathResponse,
  OneRmRequest,
  OneRmResponse,
  SessionInfo,
  SessionListResponse,
} from "./types"

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      if (body && typeof body.detail === "string") detail = body.detail
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = "ApiError"
  }
}

export interface UploadSessionArgs {
  csv: File
  annotations?: File | null
  lifter?: string
  load_lb?: number
  n_reps_prescribed?: number
}

export async function uploadSession(args: UploadSessionArgs): Promise<SessionInfo> {
  const fd = new FormData()
  fd.append("csv", args.csv)
  if (args.annotations) fd.append("annotations", args.annotations)
  if (args.lifter) fd.append("lifter", args.lifter)
  if (args.load_lb !== undefined) fd.append("load_lb", String(args.load_lb))
  if (args.n_reps_prescribed !== undefined)
    fd.append("n_reps_prescribed", String(args.n_reps_prescribed))

  const res = await fetch("/api/sessions", { method: "POST", body: fd })
  return jsonOrThrow<SessionInfo>(res)
}

export async function listSessions(): Promise<SessionInfo[]> {
  const res = await fetch("/api/sessions")
  const body = await jsonOrThrow<SessionListResponse>(res)
  return body.sessions
}

export async function deleteSession(session_id: string): Promise<void> {
  const res = await fetch(`/api/sessions/${session_id}`, { method: "DELETE" })
  if (!res.ok && res.status !== 204) {
    throw new ApiError(res.status, res.statusText)
  }
}

export async function analyzeSession(
  session_id: string,
  body: AnalyzeRequest = {}
): Promise<AnalyzeResponse> {
  const res = await fetch(`/api/sessions/${session_id}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      method: body.method ?? "D",
      include: body.include ?? ["velocity", "sticking"],
    }),
  })
  return jsonOrThrow<AnalyzeResponse>(res)
}

export async function computeOneRm(body: OneRmRequest): Promise<OneRmResponse> {
  const res = await fetch("/api/one-rm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_ids: body.session_ids,
      method: body.method ?? "D",
    }),
  })
  return jsonOrThrow<OneRmResponse>(res)
}

export async function getBarPath(session_id: string): Promise<BarPathResponse> {
  const res = await fetch(`/api/sessions/${session_id}/bar-path`, {
    method: "POST",
  })
  return jsonOrThrow<BarPathResponse>(res)
}
