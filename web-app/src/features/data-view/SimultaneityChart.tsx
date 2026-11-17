// Bar chart of the simultaneity per day. One series, so no legend: the title names it.

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { SimultaneityBucket } from '../../api/types'
import { formatDay, formatKwh, formatPercent } from '../../format'
import { texts } from '../../texts'

interface Point {
  ts: string
  label: string
  simultaneity: number | null
  shared: number
  toGrid: number
}

export function SimultaneityChart({ rows }: { rows: SimultaneityBucket[] }) {
  const data: Point[] = rows.map((row) => ({
    ts: row.ts,
    label: formatDay(row.ts),
    simultaneity: row.simultaneity,
    shared: row.shared_kwh,
    toGrid: row.total_to_grid_kwh,
  }))

  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barCategoryGap="20%">
        <CartesianGrid vertical={false} stroke="var(--grid)" />
        <XAxis
          dataKey="label"
          tickLine={false}
          axisLine={{ stroke: 'var(--axis)' }}
          tick={{ fill: 'var(--text-secondary)', fontSize: 12 }}
          minTickGap={16}
        />
        <YAxis
          domain={[0, 1]}
          ticks={[0, 0.25, 0.5, 0.75, 1]}
          tickFormatter={(value: number) => formatPercent(value)}
          tickLine={false}
          axisLine={false}
          tick={{ fill: 'var(--text-secondary)', fontSize: 12 }}
          width={48}
        />
        <Tooltip cursor={{ fill: 'var(--hover)' }} content={<ChartTooltip />} isAnimationActive={false} />
        <Bar
          dataKey="simultaneity"
          fill="var(--series-1)"
          radius={[4, 4, 0, 0]}
          maxBarSize={24}
          isAnimationActive={false}
        />
      </BarChart>
    </ResponsiveContainer>
  )
}

interface TooltipProps {
  active?: boolean
  payload?: { payload: Point }[]
}

function ChartTooltip({ active, payload }: TooltipProps) {
  if (!active || !payload?.length) return null
  const point = payload[0].payload
  return (
    <div className="tooltip">
      <div className="tooltip-title">{formatDay(point.ts, true)}</div>
      <div className="tooltip-value">
        {point.simultaneity === null ? texts.dashboard.noFeedIn : formatPercent(point.simultaneity)}
      </div>
      <div className="tooltip-row">
        <span>{texts.dashboard.sharedLabel}</span>
        <span>{formatKwh(point.shared)}</span>
      </div>
      <div className="tooltip-row">
        <span>{texts.dashboard.toGridLabel}</span>
        <span>{formatKwh(point.toGrid)}</span>
      </div>
    </div>
  )
}
