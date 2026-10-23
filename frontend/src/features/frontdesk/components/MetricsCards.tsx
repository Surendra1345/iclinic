import React from 'react'
import { CheckCircle2, CalendarClock, XCircle, Users, Activity, AlertTriangle } from 'lucide-react'
import { useDashboardStats } from '../queries/frontdeskQueries'

export const MetricsCards: React.FC = () => {
  const { data: stats, isLoading, isFetching } = useDashboardStats()

  const metrics = [
    {
      title: 'Active Booked',
      value: stats?.booked_count ?? 0,
      icon: <CheckCircle2 className="w-5 h-5 text-[#059669]" />,
      iconBg: 'bg-[#D1FAE5] border-[#A7F3D0]',
      textColor: 'text-[#059669]',
      description: 'Confirmed scheduled appointments',
    },
    {
      title: 'Rescheduled',
      value: stats?.rescheduled_count ?? 0,
      icon: <CalendarClock className="w-5 h-5 text-[#B45309]" />,
      iconBg: 'bg-[#FEF3C7] border-[#FDE68A]',
      textColor: 'text-[#B45309]',
      description: 'Moved to alternate slots',
    },
    {
      title: 'Cancelled',
      value: stats?.cancelled_count ?? 0,
      icon: <XCircle className="w-5 h-5 text-[#E11D48]" />,
      iconBg: 'bg-[#FFE4E6] border-[#FECDD3]',
      textColor: 'text-[#E11D48]',
      description: 'Slots released to inventory',
    },
    {
      title: 'Forwarded to Desk',
      value: stats?.forwarded_count ?? 0,
      icon: <AlertTriangle className="w-5 h-5 text-[#EA580C]" />,
      iconBg: 'bg-[#FFEDD5] border-[#FED7AA]',
      textColor: 'text-[#EA580C]',
      description: 'Patient transfers & escalations',
    },
    {
      title: 'Registered Patients',
      value: stats?.total_patients ?? 0,
      icon: <Users className="w-5 h-5 text-[#0D9488]" />,
      iconBg: 'bg-[#CCFBF1] border-[#99F6E4]',
      textColor: 'text-[#0D9488]',
      description: `${stats?.total_locations ?? 4} Branch locations active`,
    },
  ]

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-xs text-[#64748B] px-1">
        <span className="flex items-center gap-1.5 font-semibold uppercase tracking-wider text-[#475569]">
          <Activity className="w-3.5 h-3.5 text-[#0D9488]" />
          Real-Time Frontdesk Statistics
        </span>
        {isFetching && (
          <span className="inline-flex items-center gap-1 text-[#0D9488] font-medium text-[11px]">
            <span className="w-1.5 h-1.5 rounded-full bg-[#0D9488] animate-pulse" />
            Live Syncing...
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        {metrics.map((m, idx) => (
          <div
            key={idx}
            className="p-5 flex flex-col justify-between bg-white border border-[#E2E8F0] rounded-2xl shadow-[var(--shadow-card)] transition-all hover:border-[#CBD5E1]"
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-[#475569]">{m.title}</span>
              <div className={`p-2 rounded-xl border ${m.iconBg}`}>
                {m.icon}
              </div>
            </div>
            <div className="mt-4">
              <div className={`text-3xl font-bold tracking-tight ${m.textColor}`}>
                {isLoading ? '...' : m.value}
              </div>
              <p className="text-xs text-[#64748B] mt-1">{m.description}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
