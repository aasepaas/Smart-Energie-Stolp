// Data import (component 'Data import' in C4 3.1): upload a CSV and follow the import.

import { useState, type FormEvent } from 'react'
import { api, ApiError } from '../../api/client'
import type { ImportRecord } from '../../api/types'
import { texts } from '../../texts'

const POLL_MS = 1000
const MAX_POLLS = 600 // 10 minutes

type Phase =
  | { kind: 'idle' }
  | { kind: 'uploading' }
  | { kind: 'processing' }
  | { kind: 'done'; message: string }
  | { kind: 'error'; message: string }

interface Props {
  onImported: (record: ImportRecord) => void
}

export function UploadPanel({ onImported }: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' })
  const [inputKey, setInputKey] = useState(0) // changing the key empties the file input

  const busy = phase.kind === 'uploading' || phase.kind === 'processing'

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!file) return
    setPhase({ kind: 'uploading' })
    try {
      const accepted = await api.upload(file)
      setPhase({ kind: 'processing' })
      const record = await waitForImport(accepted.import_id)
      if (record.status === 'succeeded') {
        setPhase({ kind: 'done', message: texts.import.succeeded(record.row_count ?? 0, record.new_meter_count ?? 0) })
        onImported(record)
      } else {
        setPhase({ kind: 'error', message: texts.import.failed(record.error_message) })
        onImported(record)
      }
      setFile(null)
      setInputKey((key) => key + 1)
    } catch (error) {
      const message = error instanceof ApiError && error.status === 409
        ? texts.import.duplicate
        : error instanceof Error ? error.message : String(error)
      setPhase({ kind: 'error', message })
    }
  }

  return (
    <section className="card" aria-labelledby="import-title">
      <h2 id="import-title">{texts.import.title}</h2>
      <p className="muted">{texts.import.intro}</p>
      <form className="upload-form" onSubmit={submit}>
        <label className="file-field">
          <span className="visually-hidden">{texts.import.chooseFile}</span>
          <input
            key={inputKey}
            type="file"
            accept=".csv,text/csv"
            disabled={busy}
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <button type="submit" disabled={!file || busy}>
          {texts.import.submit}
        </button>
      </form>
      <p className={`status status-${phase.kind}`} role="status" aria-live="polite">
        {phase.kind === 'uploading' && texts.import.uploading}
        {phase.kind === 'processing' && texts.import.processing}
        {(phase.kind === 'done' || phase.kind === 'error') && phase.message}
      </p>
    </section>
  )
}

async function waitForImport(importId: string): Promise<ImportRecord> {
  for (let poll = 0; poll < MAX_POLLS; poll++) {
    const record = await api.importStatus(importId)
    if (record.status !== 'running') return record
    await new Promise((resolve) => setTimeout(resolve, POLL_MS))
  }
  throw new Error(texts.import.failed(null))
}
