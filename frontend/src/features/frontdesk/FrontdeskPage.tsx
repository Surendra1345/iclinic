import React, { useState } from 'react'
import {
  Stethoscope,
  Activity,
  ArrowLeft,
  ShieldCheck,
  Calendar,
  Users,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { MetricsCards } from './components/MetricsCards'
import { AppointmentsTable } from './components/AppointmentsTable'
import { PatientsTable } from './components/PatientsTable'
import { LocationRoster } from './components/LocationRoster'
import { Badge } from '../../components/ui/Badge'
import { ENV } from '../../config/env'
import { useDashboardStats } from './queries/frontdeskQueries'

export const FrontdeskPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'appointments' | 'patients'>('appointments')
  const { data: stats } = useDashboardStats()

  return (
    <div className="min-h-screen bg-[#070b14] text-slate-100 selection:bg-teal-500/30 selection:text-teal-200">
      {/* Frontdesk Header */}
      <header className="sticky top-0 z-40 border-b border-slate-800/80 bg-slate-950/80 backdrop-blur-xl">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-teal-500 to-emerald-400 flex items-center justify-center text-slate-950 font-bold shadow-md shadow-teal-500/20">
              <Stethoscope className="w-5 h-5 text-slate-950" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-white text-base tracking-tight">
                  {ENV.CLINIC_NAME}
                </span>
                <Badge variant="teal" className="text-[10px] py-0.5">
                  Frontdesk Console
                </Badge>
              </div>
              <p className="text-[11px] text-slate-400 hidden sm:block">
                Chennai Multi-Branch Appointment Operations
              </p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-medium">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span>Real-time DB Sync</span>
            </div>

            <Link
              to="/patients"
              className="flex items-center gap-1.5 text-xs font-medium text-slate-300 hover:text-white px-3.5 py-2 rounded-xl bg-slate-900 border border-slate-800 hover:border-teal-500/40 transition-all shadow-sm"
            >
              <ArrowLeft className="w-3.5 h-3.5 text-teal-400" />
              <span>Patient Experience</span>
            </Link>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* Subheader */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800/80 pb-5">
          <div>
            <h1 className="text-2xl sm:text-3xl font-bold text-white tracking-tight">
              Appointment Schedule & Intake
            </h1>
            <p className="text-xs sm:text-sm text-slate-400 mt-1">
              Live monitoring of incoming patient calls, web chat bookings, reschedules, and registered patient roster
            </p>
          </div>

          <div className="flex items-center gap-2 text-xs text-slate-400 bg-slate-900/90 px-3.5 py-2 rounded-xl border border-slate-800 shrink-0">
            <Activity className="w-4 h-4 text-teal-400 animate-pulse" />
            <span>Auto-refreshing every 5 seconds</span>
          </div>
        </div>

        {/* 4 KPI Metrics Cards */}
        <MetricsCards />

        {/* Tab Navigation between Appointments and Patients */}
        <div className="space-y-4">
          <div className="flex items-center gap-2 p-1 bg-slate-900/90 border border-slate-800 rounded-2xl w-fit">
            <button
              type="button"
              onClick={() => setActiveTab('appointments')}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs sm:text-sm font-semibold transition-all ${
                activeTab === 'appointments'
                  ? 'bg-teal-500 text-slate-950 shadow-md shadow-teal-500/20'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
              }`}
            >
              <Calendar className="w-4 h-4" />
              <span>Appointments Schedule</span>
              <span
                className={`ml-1 text-[11px] px-2 py-0.5 rounded-full ${
                  activeTab === 'appointments'
                    ? 'bg-slate-950/20 text-slate-950'
                    : 'bg-slate-800 text-slate-300'
                }`}
              >
                {stats?.total_appointments ?? 0}
              </span>
            </button>

            <button
              type="button"
              onClick={() => setActiveTab('patients')}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs sm:text-sm font-semibold transition-all ${
                activeTab === 'patients'
                  ? 'bg-teal-500 text-slate-950 shadow-md shadow-teal-500/20'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
              }`}
            >
              <Users className="w-4 h-4" />
              <span>Registered Patients</span>
              <span
                className={`ml-1 text-[11px] px-2 py-0.5 rounded-full ${
                  activeTab === 'patients'
                    ? 'bg-slate-950/20 text-slate-950'
                    : 'bg-slate-800 text-slate-300'
                }`}
              >
                {stats?.total_patients ?? 0}
              </span>
            </button>
          </div>

          {/* Active Tab Content */}
          {activeTab === 'appointments' ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-white tracking-tight">
                  Patient Appointments List
                </h2>
                <span className="text-xs text-slate-500">
                  Filtered by status, branch location, and search keyword
                </span>
              </div>
              <AppointmentsTable />
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-white tracking-tight">
                  Clinic Patient Roster
                </h2>
                <span className="text-xs text-slate-500">
                  All registered patients across Anna Nagar, T. Nagar, Velachery, and Tambaram
                </span>
              </div>
              <PatientsTable />
            </div>
          )}
        </div>

        {/* Clinic Branches & Doctor Rosters */}
        <LocationRoster />
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/80 bg-slate-950/60 py-6 mt-12">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-slate-500">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-teal-400" />
            <span>{ENV.CLINIC_NAME} Frontdesk Operations Portal</span>
          </div>
          <span>Active Branches: Anna Nagar, T. Nagar, Velachery, Tambaram</span>
        </div>
      </footer>
    </div>
  )
}
