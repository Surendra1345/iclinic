import React from 'react'
import { CheckCircle2, CalendarClock, XCircle, Users, Activity } from 'lucide-react'
import { Card } from '../../../components/ui/Card'
import { useDashboardStats } from '../queries/frontdeskQueries'

export const MetricsCards: React.FC = () => {
  const { data: stats, isLoading, isFetching } = useDashboardStats()

  const metrics = [
    {
      title: 'Active Booked',
      value: stats?.booked_count ?? 0,
      icon: <CheckCircle2 className="w-5 h-5 text-emerald-400" />,
      glow: 'emerald' as const,
      textColor: 'text-emerald-400',
      description: 'Confirmed scheduled appointments',
    },
    {
      title: 'Rescheduled',
      value: stats?.rescheduled_count ?? 0,
      icon: <CalendarClock className="w-5 h-5 text-amber-400" />,
      glow: 'amber' as const,
      textColor: 'text-amber-400',
      description: 'Moved to alternate slots',
    },
    {
      title: 'Cancelled',
      value: stats?.cancelled_count ?? 0,
      icon: <XCircle className="w-5 h-5 text-rose-400" />,
      glow: 'rose' as const,
      textColor: 'text-rose-400',
      description: 'Slots released to inventory',
    },
    {
      title: 'Registered Patients',
      value: stats?.total_patients ?? 0,
      icon: <Users className="w-5 h-5 text-teal-400" />,
      glow: 'teal' as const,
      textColor: 'text-teal-400',
      description: `${stats?.total_locations ?? 4} Branch locations active`,
    },
  ]

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-xs text-slate-400 px-1">
        <span className="flex items-center gap-1.5 font-medium uppercase tracking-wider">
          <Activity className="w-3.5 h-3.5 text-teal-400" />
          Real-Time Frontdesk Statistics
        </span>
        {isFetching && (
          <span className="inline-flex items-center gap-1 text-teal-400 animate-pulse text-[11px]">
            <span className="w-1.5 h-1.5 rounded-full bg-teal-400" />
            Live Syncing...
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {metrics.map((m, idx) => (
          <Card key={idx} glow={m.glow} className="p-5 flex flex-col justify-between">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-300">{m.title}</span>
              <div className="p-2 rounded-xl bg-slate-900 border border-slate-800">
                {m.icon}
              </div>
            </div>
            <div className="mt-4">
              <div className={`text-3xl font-bold tracking-tight ${m.textColor}`}>
                {isLoading ? '...' : m.value}
              </div>
              <p className="text-xs text-slate-400 mt-1">{m.description}</p>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
