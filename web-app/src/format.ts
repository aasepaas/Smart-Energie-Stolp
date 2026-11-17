// Formatting and period helpers. Dates in the UI are Dutch local dates; the API works
// with UTC timestamps and [start, end) periods.

const TIME_ZONE = 'Europe/Amsterdam'

const percent = new Intl.NumberFormat('nl-NL', { style: 'percent', maximumFractionDigits: 1 })

export function formatPercent(value: number | null): string {
  return value === null ? '–' : percent.format(value)
}

export function formatKwh(value: number): string {
  const digits = Math.abs(value) < 10 ? 2 : Math.abs(value) < 100 ? 1 : 0
  return `${value.toLocaleString('nl-NL', { maximumFractionDigits: digits })} kWh`
}

export function formatDay(ts: string, withWeekday = false): string {
  return new Date(ts).toLocaleDateString('nl-NL', {
    timeZone: TIME_ZONE,
    day: 'numeric',
    month: 'short',
    ...(withWeekday ? { weekday: 'short' } : {}),
  })
}

export function formatDateTime(ts: string): string {
  return new Date(ts).toLocaleString('nl-NL', {
    timeZone: TIME_ZONE,
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** A period of whole local days, both ends included, as yyyy-mm-dd strings. */
export interface Period {
  from: string
  to: string
}

/** yyyy-mm-dd of a moment in Dutch local time. */
export function localDate(moment: Date): string {
  // sv-SE formats dates as yyyy-mm-dd
  return moment.toLocaleDateString('sv-SE', { timeZone: TIME_ZONE })
}

/** Start and end of a period as UTC instants: [local midnight of from, local midnight after to). */
export function periodRange(period: Period): { start: Date; end: Date } {
  return { start: localMidnight(period.from), end: localMidnight(addDays(period.to, 1)) }
}

/** The whole days covered by an import (period_end is exclusive). */
export function periodOf(start: string, end: string): Period {
  return { from: localDate(new Date(start)), to: localDate(new Date(new Date(end).getTime() - 1)) }
}

export function lastDays(days: number, today = new Date()): Period {
  const to = localDate(today)
  return { from: addDays(to, 1 - days), to }
}

export function isValidPeriod(period: Period): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(period.from) && /^\d{4}-\d{2}-\d{2}$/.test(period.to)
    && period.from <= period.to
}

function addDays(day: string, days: number): string {
  const [y, m, d] = day.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10)
}

/** The UTC instant of 00:00 Dutch time on a yyyy-mm-dd day (handles summer time). */
function localMidnight(day: string): Date {
  const [y, m, d] = day.split('-').map(Number)
  const utcMidnight = Date.UTC(y, m - 1, d)
  // Offset of Amsterdam at that moment, e.g. +01:00 in winter and +02:00 in summer
  const offsetText = new Intl.DateTimeFormat('en-US', { timeZone: TIME_ZONE, timeZoneName: 'longOffset' })
    .formatToParts(new Date(utcMidnight))
    .find((part) => part.type === 'timeZoneName')?.value ?? 'GMT'
  const match = /GMT([+-])(\d{2}):(\d{2})/.exec(offsetText)
  const offsetMinutes = match ? (match[1] === '-' ? -1 : 1) * (Number(match[2]) * 60 + Number(match[3])) : 0
  return new Date(utcMidnight - offsetMinutes * 60_000)
}
