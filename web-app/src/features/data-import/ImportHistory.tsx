// The most recent imports with their result (import_log).

import type { ImportRecord } from '../../api/types'
import { formatDateTime, formatDay, periodOf } from '../../format'
import { texts } from '../../texts'

export function ImportHistory({ imports }: { imports: ImportRecord[] }) {
  const columns = texts.history.columns
  return (
    <section className="card" aria-labelledby="history-title">
      <h2 id="history-title">{texts.history.title}</h2>
      {imports.length === 0 ? (
        <p className="muted">{texts.history.empty}</p>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">{columns.started}</th>
                <th scope="col">{columns.file}</th>
                <th scope="col">{columns.status}</th>
                <th scope="col" className="number">{columns.rows}</th>
                <th scope="col">{columns.period}</th>
              </tr>
            </thead>
            <tbody>
              {imports.map((record) => (
                <tr key={record.id}>
                  <td>{formatDateTime(record.started_at)}</td>
                  <td className="file-name">{record.file_name}</td>
                  <td>
                    <span className={`badge badge-${record.status}`}>{texts.history.status[record.status]}</span>
                  </td>
                  <td className="number">{record.row_count?.toLocaleString('nl-NL') ?? '–'}</td>
                  <td>{period(record)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function period(record: ImportRecord): string {
  if (!record.period_start || !record.period_end) return '–'
  const { from, to } = periodOf(record.period_start, record.period_end)
  return `${formatDay(`${from}T12:00:00Z`)} – ${formatDay(`${to}T12:00:00Z`)}`
}
