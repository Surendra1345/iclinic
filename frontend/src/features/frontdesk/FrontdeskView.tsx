import React from 'react'
import { MetricsCards } from './components/MetricsCards'
import { AppointmentsTable } from './components/AppointmentsTable'
import { LocationRoster } from './components/LocationRoster'
import { Badge } from '../../components/ui/Badge'
import { Activity } from 'lucide-react'

export const FrontdeskView: React.FC = () => {
  return (
    <div className="space-y-8 animate-fadeIn">
      {/* Frontdesk Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h2 className="text-2xl sm:text-3xl font-bold text-white tracking-tight">
              Frontdesk Operations Console
            </h2>
            <Badge variant="teal">Live Synced</Badge>
          </div>
          <p className="text-xs sm:text-sm text-slate-400">
            Real-time appointment intake monitoring across Chennai branch locations
          </p>
        </div>

        <div className="flex items-center gap-2 text-xs text-slate-400 bg-slate-900 px-3.5 py-2 rounded-xl border border-slate-800">
          <Activity className="w-4 h-4 text-teal-400 animate-pulse" />
          <span>Polling clinical database every 5 seconds</span>
        </div>
      </div>

      {/* KPI Stats Cards */}
      <MetricsCards />

      {/* Main Appointments Table with filters */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-white tracking-tight">
            Patient Appointments Schedule
          </h3>
        </div>
        <AppointmentsTable />
      </div>

      {/* Clinic Branches and Doctor Rosters */}
      <LocationRoster />
    </div>
  )
}
