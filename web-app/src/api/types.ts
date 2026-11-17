// Response shapes of the Frontend API (see services/frontend-api/README.md).

export interface SimultaneityBucket {
  ts: string
  total_to_grid_kwh: number
  total_from_grid_kwh: number
  shared_kwh: number
  simultaneity: number | null
  meter_count: number
  quarter_count: number
}

export interface SimultaneityTotals {
  total_to_grid_kwh: number
  total_from_grid_kwh: number
  shared_kwh: number
  simultaneity: number | null
  quarter_count: number
}

export interface SimultaneityResponse {
  summary: SimultaneityTotals
  rows: SimultaneityBucket[]
}

export type ImportStatus = 'running' | 'succeeded' | 'failed'

export interface ImportRecord {
  id: string
  file_name: string
  status: ImportStatus
  period_start: string | null
  period_end: string | null
  row_count: number | null
  new_meter_count: number | null
  error_message: string | null
  started_at: string
}

export interface UploadAccepted {
  import_id: string
  status: string
  file_name: string
}
