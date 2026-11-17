// User interface (component 'User interface' in C4 3.1), demo version: one admin page,
// no router and no route guards yet.

import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ImportRecord } from '../api/types'
import { ImportHistory } from '../features/data-import/ImportHistory'
import { UploadPanel } from '../features/data-import/UploadPanel'
import { SimultaneityDashboard } from '../features/data-view/SimultaneityDashboard'
import { lastDays, periodOf, type Period } from '../format'
import { texts } from '../texts'

const DEFAULT_DAYS = 28

export function App() {
  const [imports, setImports] = useState<ImportRecord[]>([])
  const [period, setPeriod] = useState<Period | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const loadImports = useCallback(async () => {
    try {
      const records = await api.imports()
      setImports(records)
      setError(null)
      return records
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      return []
    }
  }, [])

  // Start with the period of the most recent successful import, so there is data to show
  useEffect(() => {
    loadImports().then((records) => {
      const latest = records.find((r) => r.status === 'succeeded' && r.period_start && r.period_end)
      setPeriod(latest ? periodOf(latest.period_start!, latest.period_end!) : lastDays(DEFAULT_DAYS))
    })
  }, [loadImports])

  function imported(record: ImportRecord) {
    loadImports()
    if (record.status === 'succeeded' && record.period_start && record.period_end) {
      setPeriod(periodOf(record.period_start, record.period_end))
    }
    setRefreshKey((key) => key + 1) // also reload when the period stays the same
  }

  return (
    <div className="page">
      <header className="page-header">
        <span className="app-title">{texts.appTitle}</span>
        <h1>{texts.pageTitle}</h1>
      </header>
      <main>
        {error && (
          <p className="banner" role="alert">
            {error}
          </p>
        )}
        <UploadPanel onImported={imported} />
        {period && <SimultaneityDashboard period={period} onPeriodChange={setPeriod} refreshKey={refreshKey} />}
        <ImportHistory imports={imports} />
      </main>
    </div>
  )
}
