export type Method = "A" | "B" | "C" | "D"

export type IncludeKey = "rep_counting" | "velocity" | "sticking"

export interface SessionInfo {
  session_id: string
  filename: string
  fs_hz: number
  duration_s: number
  n_samples: number
  has_annotations: boolean
  lifter: string | null
  load_lb: number | null
  n_reps_prescribed: number | null
  uploaded_at: string
}

export interface SessionListResponse {
  sessions: SessionInfo[]
}

export interface RepBoundary {
  num: number
  chest_s: number
  lockout_s: number
  peak_s: number
}

export interface PlotData {
  t: number[]
  vy: number[]
  ay_lin: number[]
  gyro_mag: number[]
}

export interface RepMetrics {
  num: number
  chest_s: number
  top_s: number
  duration_s: number
  mcv: number | null
  pcv: number | null
  mpv: number | null
  rom_m: number | null
  tpv_s: number | null
  emv: number | null
  erom_m: number | null
  ecc_dur_s: number | null
  propulsive_frac: number | null
}

export interface StickingPoint {
  num: number
  chest_s: number
  top_s: number
  pcv: number | null
  pcv_t: number | null
  sp_t: number | null
  sp_v: number | null
  sp_frac: number | null
  sp_depth: number
  sp_rel_depth: number
  post_amp: number
  has_sticking: boolean
}

export interface AnalyzeResponse {
  session_id: string
  method: Method
  rep_boundaries: RepBoundary[]
  reps?: RepMetrics[]
  sticking?: StickingPoint[]
  plot_data: PlotData
}

export interface AnalyzeRequest {
  method?: Method
  include?: IncludeKey[]
}

export interface EstimatorOut {
  name: string
  one_rm_lb: number | null
  slope: number | null
  intercept: number | null
  r2: number | null
  mvt: number | null
  x_points: number[]
  y_points: number[]
  notes: string
  valid: boolean
}

export interface SessionSummary {
  session_id: string
  name: string
  lifter: string
  load_lb: number
  n_reps_prescribed: number
  n_reps_detected: number
  best_mpv: number | null
  best_mcv: number | null
  best_pcv: number | null
  top2_mpv: number | null
  rep1_mpv: number | null
  last_mpv: number | null
  vl_frac: number | null
  rep_mpv: number[]
  rep_mcv: number[]
  rep_pcv: number[]
}

export interface OneRmResponse {
  lifter: string
  consensus_one_rm_lb: number | null
  ci95: (number | null)[]
  method_used: Method
  notes: string
  estimators: EstimatorOut[]
  sessions: SessionSummary[]
}

export interface OneRmRequest {
  session_ids: string[]
  method?: Method
}
