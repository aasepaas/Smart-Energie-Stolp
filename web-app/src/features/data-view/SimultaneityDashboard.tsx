// Data view (component 'Data view' in C4 3.1), demo version: community simultaneity
// over a period, as one headline figure, two tiles and a bar per day.

import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { SimultaneityResponse } from '../../api/types'
import { formatDay, formatKwh, formatPercent, isValidPeriod, periodRange, type Period } from '../../format'
import { texts } from '../../texts'
import { SimultaneityChart } from './SimultaneityChart'

type State =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; data: SimultaneityResponse }

interface Props {
  period: Period
  onPeriodChange: (period: Period) => void
  refreshKey: number
}

export function SimultaneityDashboard({ period, onPeriodChange, refreshKey }: Props) {
  const [state, setState] = useState<State>({ kind: 'loading' })
  const valid = isValidPeriod(period)

  useEffect(() => {
    if (!valid) return
    let cancelled = false
    setState({ kind: 'loading' })
    const { start, end } = periodRange(period)
    api.simultaneity(start, end, 'day').then(
      (data) => !cancelled && setState({ kind: 'ready', data }),
      (error: Error) => !cancelled && setState({ kind: 'error', message: error.message }),
    )
    return () => {
      cancelled = true
    }
  }, [period, valid, refreshKey])

  return (
    <section className="card" aria-labelledby="dashboard-title">
      <div className="card-header">
        <div>
          <h2 id="dashboard-title">{texts.dashboard.title}</h2>
          <p className="muted">{texts.dashboard.explanation}</p>
        </div>
        <div className="period">
          <label>
            <span>{texts.dashboard.from}</span>
            <input
              type="date"
              value={period.from}
              onChange={(event) => onPeriodChange({ ...period, from: event.target.value })}
            />
          </label>
          <label>
            <span>{texts.dashboard.to}</span>
            <input
              type="date"
              value={period.to}
              onChange={(event) => onPeriodChange({ ...period, to: event.target.value })}
            />
          </label>
        </div>
      </div>

      {!valid ? (
        <p className="status status-error">{texts.dashboard.invalidPeriod}</p>
      ) : state.kind === 'loading' ? (
        <p className="muted">{texts.dashboard.loading}</p>
      ) : state.kind === 'error' ? (
        <p className="status status-error" role="alert">{state.message}</p>
      ) : state.data.rows.length === 0 ? (
        <p className="muted">{texts.dashboard.empty}</p>
      ) : (
        <Results data={state.data} period={period} />
      )}
    </section>
  )
}

function Results({ data, period }: { data: SimultaneityResponse; period: Period }) {
  const { summary, rows } = data
  const columns = texts.dashboard.columns
  const label = texts.dashboard.chartLabel(
    formatDay(`${period.from}T12:00:00Z`), formatDay(`${period.to}T12:00:00Z`),
  )
  return (
    <>
      <div className="figures">
        <div className="hero">
          <div className="figure-label">{texts.dashboard.heroLabel}</div>
          <div className="hero-value">{formatPercent(summary.simultaneity)}</div>
        </div>
        <Tile label={texts.dashboard.sharedLabel} value={formatKwh(summary.shared_kwh)} />
        <Tile label={texts.dashboard.toGridLabel} value={formatKwh(summary.total_to_grid_kwh)} />
        <Tile label={texts.dashboard.fromGridLabel} value={formatKwh(summary.total_from_grid_kwh)} />
      </div>

      <figure className="chart" aria-label={label}>
        <figcaption>{texts.dashboard.chartTitle}</figcaption>
        <SimultaneityChart rows={rows} />
      </figure>

      <details className="table-view">
        <summary>{texts.dashboard.showTable}</summary>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">{columns.day}</th>
                <th scope="col" className="number">{columns.simultaneity}</th>
                <th scope="col" className="number">{columns.shared}</th>
                <th scope="col" className="number">{columns.toGrid}</th>
                <th scope="col" className="number">{columns.fromGrid}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.ts}>
                  <td>{formatDay(row.ts, true)}</td>
                  <td className="number">{formatPercent(row.simultaneity)}</td>
                  <td className="number">{row.shared_kwh.toLocaleString('nl-NL')}</td>
                  <td className="number">{row.total_to_grid_kwh.toLocaleString('nl-NL')}</td>
                  <td className="number">{row.total_from_grid_kwh.toLocaleString('nl-NL')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  )
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="tile">
      <div className="figure-label">{label}</div>
      <div className="tile-value">{value}</div>
    </div>
  )
}
