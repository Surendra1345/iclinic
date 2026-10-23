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
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#E2E8F0] pb-5">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h2 className="text-2xl sm:text-3xl font-bold text-[#0F172A] tracking-tight">
              Frontdesk Operations Console
            </h2>
            <Badge variant="teal">Live Synced</Badge>
          </div>
          <p className="text-xs sm:text-sm text-[#475569]">
            Real-time appointment intake monitoring across Chennai branch locations
          </p>
        </div>

        <div className="flex items-center gap-2 text-xs text-[#475569] bg-white px-3.5 py-2 rounded-xl border border-[#E2E8F0] shadow-sm">
          <Activity className="w-4 h-4 text-[#14B8A6] animate-pulse" />
          <span>Polling clinical database every 5 seconds</span>
        </div>
      </div>

      {/* KPI Stats Cards */}
      <MetricsCards />

      {/* Main Appointments Table with filters */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-[#0F172A] tracking-tight">
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
