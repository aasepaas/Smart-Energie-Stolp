import { describe, expect, it } from 'vitest'
import { formatKwh, formatPercent, isValidPeriod, lastDays, periodOf, periodRange } from './format'

describe('periodRange', () => {
  it('runs from Dutch midnight to the midnight after the last day', () => {
    const { start, end } = periodRange({ from: '2026-01-10', to: '2026-01-11' })
    expect(start.toISOString()).toBe('2026-01-09T23:00:00.000Z') // winter time, +01:00
    expect(end.toISOString()).toBe('2026-01-11T23:00:00.000Z')
  })

  it('handles the switch to summer time', () => {
    const { start, end } = periodRange({ from: '2026-03-16', to: '2026-04-12' })
    expect(start.toISOString()).toBe('2026-03-15T23:00:00.000Z')
    expect(end.toISOString()).toBe('2026-04-12T22:00:00.000Z') // summer time, +02:00
  })

  it('crosses a month end', () => {
    expect(periodRange({ from: '2026-06-30', to: '2026-06-30' }).end.toISOString())
      .toBe('2026-06-30T22:00:00.000Z')
  })
})

describe('periodOf', () => {
  it('turns an import period [start, end) into whole local days', () => {
    expect(periodOf('2026-03-15T23:00:00Z', '2026-04-12T22:00:00Z'))
      .toEqual({ from: '2026-03-16', to: '2026-04-12' })
  })
})

describe('lastDays', () => {
  it('ends today and includes it', () => {
    expect(lastDays(7, new Date('2026-11-17T10:00:00Z'))).toEqual({ from: '2026-11-11', to: '2026-11-17' })
  })
})

describe('isValidPeriod', () => {
  it('needs two dates with the end on or after the start', () => {
    expect(isValidPeriod({ from: '2026-01-01', to: '2026-01-01' })).toBe(true)
    expect(isValidPeriod({ from: '2026-01-02', to: '2026-01-01' })).toBe(false)
    expect(isValidPeriod({ from: '', to: '2026-01-01' })).toBe(false)
  })
})

describe('formatting', () => {
  it('uses Dutch number formatting', () => {
    expect(formatPercent(0.3119)).toBe('31,2%')
    expect(formatPercent(null)).toBe('–')
    expect(formatKwh(2594.581)).toBe('2.595 kWh')
    expect(formatKwh(8.5)).toBe('8,5 kWh')
  })
})
