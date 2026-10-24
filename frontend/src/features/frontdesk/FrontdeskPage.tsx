import React, { useState } from 'react'
import {
  Stethoscope,
  Activity,
  ArrowLeft,
  ShieldCheck,
  Calendar,
  Users,
  AlertTriangle,
  LogOut,
  MessageSquare,
} from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { authService } from '../auth/authService'
import { MetricsCards } from './components/MetricsCards'
import { AppointmentsTable } from './components/AppointmentsTable'
import { PatientsTable } from './components/PatientsTable'
import { ForwardedRequestsTable } from './components/ForwardedRequestsTable'
import { ConversationsTable } from './components/ConversationsTable'
import { LocationRoster } from './components/LocationRoster'
import { Badge } from '../../components/ui/Badge'
import { ENV } from '../../config/env'
import { useDashboardStats } from './queries/frontdeskQueries'

export const FrontdeskPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'appointments' | 'patients' | 'conversations' | 'forwarded'>('appointments')
  const { data: stats } = useDashboardStats()
  const navigate = useNavigate()

  const handleLogout = () => {
    authService.logout()
    navigate('/frontdesk/login', { replace: true })
  }

  return (
    <div className="min-h-screen bg-[#F6F9FB] text-[#0F172A] selection:bg-[#CCFBF1] selection:text-[#0D9488]">
      {/* Frontdesk Header */}
      <header className="sticky top-0 z-40 border-b border-[#E2E8F0] bg-white/95 backdrop-blur-md shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-[#14B8A6] flex items-center justify-center text-white font-bold shadow-sm">
              <Stethoscope className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-[#0F172A] text-base tracking-tight">
                  {ENV.CLINIC_NAME}
                </span>
                <Badge variant="teal" className="text-[10px] py-0.5">
                  Frontdesk Console
                </Badge>
              </div>
              <p className="text-[11px] text-[#64748B] hidden sm:block">
                Chennai Multi-Branch Appointment Operations
              </p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-full bg-[#D1FAE5] border border-[#A7F3D0] text-[#059669] text-xs font-medium">
              <span className="w-2 h-2 rounded-full bg-[#059669] animate-pulse" />
              <span>Real-time DB Sync</span>
            </div>

            <Link
              to="/patients"
              className="flex items-center gap-1.5 text-xs font-semibold text-[#475569] hover:text-[#0F172A] px-3.5 py-2 rounded-xl bg-white border border-[#E2E8F0] hover:border-[#CBD5E1] transition-all shadow-sm"
            >
              <ArrowLeft className="w-3.5 h-3.5 text-[#0D9488]" />
              <span>Patient Experience</span>
            </Link>

            <button
              type="button"
              onClick={handleLogout}
              className="flex items-center gap-1.5 text-xs font-semibold text-[#475569] hover:text-[#E11D48] px-3.5 py-2 rounded-xl bg-white border border-[#E2E8F0] hover:border-[#FECDD3] transition-all shadow-sm cursor-pointer"
            >
              <LogOut className="w-3.5 h-3.5" />
              <span>Log out</span>
            </button>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* Subheader */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#E2E8F0] pb-5">
          <div>
            <h1 className="text-2xl sm:text-3xl font-bold text-[#0F172A] tracking-tight">
              Appointment Schedule & Intake
            </h1>
            <p className="text-xs sm:text-sm text-[#475569] mt-1">
              Live monitoring of incoming patient calls, web chat bookings, reschedules, and registered patient roster
            </p>
          </div>

          <div className="flex items-center gap-2 text-xs text-[#64748B] bg-white px-3.5 py-2 rounded-xl border border-[#E2E8F0] shrink-0 shadow-xs">
            <Activity className="w-4 h-4 text-[#0D9488]" />
            <span>Auto-refreshing every 5 seconds</span>
          </div>
        </div>

        {/* 5 KPI Metrics Cards */}
        <MetricsCards />

        {/* Tab Navigation between Appointments, Patients, and Forwarded */}
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 p-1.5 bg-[#F1F5F9] border border-[#E2E8F0] rounded-2xl w-fit shadow-xs">
            <button
              type="button"
              onClick={() => setActiveTab('appointments')}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs sm:text-sm font-semibold transition-all cursor-pointer ${
                activeTab === 'appointments'
                  ? 'bg-[#0F766E] text-white shadow-sm'
                  : 'text-[#475569] hover:text-[#0F172A] hover:bg-white'
              }`}
            >
              <Calendar className="w-4 h-4" />
              <span>Appointments Schedule</span>
              <span
                className={`ml-1 text-[11px] px-2 py-0.5 rounded-full font-bold ${
                  activeTab === 'appointments'
                    ? 'bg-white/20 text-white'
                    : 'bg-white text-[#475569] border border-[#E2E8F0]'
                }`}
              >
                {stats?.total_appointments ?? 0}
              </span>
            </button>

            <button
              type="button"
              onClick={() => setActiveTab('patients')}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs sm:text-sm font-semibold transition-all cursor-pointer ${
                activeTab === 'patients'
                  ? 'bg-[#0F766E] text-white shadow-sm'
                  : 'text-[#475569] hover:text-[#0F172A] hover:bg-white'
              }`}
            >
              <Users className="w-4 h-4" />
              <span>Registered Patients</span>
              <span
                className={`ml-1 text-[11px] px-2 py-0.5 rounded-full font-bold ${
                  activeTab === 'patients'
                    ? 'bg-white/20 text-white'
                    : 'bg-white text-[#475569] border border-[#E2E8F0]'
                }`}
              >
                {stats?.total_patients ?? 0}
              </span>
            </button>

            <button
              type="button"
              onClick={() => setActiveTab('conversations')}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs sm:text-sm font-semibold transition-all cursor-pointer ${
                activeTab === 'conversations'
                  ? 'bg-[#0F766E] text-white shadow-sm'
                  : 'text-[#475569] hover:text-[#0F172A] hover:bg-white'
              }`}
            >
              <MessageSquare className="w-4 h-4" />
              <span>Conversations</span>
            </button>

            <button
              type="button"
              onClick={() => setActiveTab('forwarded')}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs sm:text-sm font-semibold transition-all relative cursor-pointer ${
                activeTab === 'forwarded'
                  ? 'bg-[#EA580C] text-white shadow-sm'
                  : 'text-[#475569] hover:text-[#0F172A] hover:bg-white'
              }`}
            >
              <AlertTriangle className={`w-4 h-4 ${activeTab === 'forwarded' ? 'text-white' : 'text-[#EA580C]'}`} />
              <span>Forwarded Requests</span>
              <span
                className={`ml-1 text-[11px] font-bold px-2 py-0.5 rounded-full ${
                  activeTab === 'forwarded'
                    ? 'bg-white/20 text-white'
                    : stats?.forwarded_count && stats.forwarded_count > 0
                    ? 'bg-[#FFEDD5] text-[#EA580C] border border-[#FED7AA]'
                    : 'bg-white text-[#475569] border border-[#E2E8F0]'
                }`}
              >
                {stats?.forwarded_count ?? 0}
              </span>
            </button>
          </div>

          {/* Active Tab Content */}
          {activeTab === 'appointments' ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-[#0F172A] tracking-tight">
                  Patient Appointments List
                </h2>
                <span className="text-xs text-[#64748B]">
                  Filtered by status, branch location, and search keyword
                </span>
              </div>
              <AppointmentsTable />
            </div>
          ) : activeTab === 'conversations' ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-[#0F172A] tracking-tight">
                  Conversation Records
                </h2>
                <span className="text-xs text-[#64748B]">
                  Chat, voice, and outbound call transcripts with state timeline and step log
                </span>
              </div>
              <ConversationsTable />
            </div>
          ) : activeTab === 'patients' ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-[#0F172A] tracking-tight">
                  Clinic Patient Roster
                </h2>
                <span className="text-xs text-[#64748B]">
                  All registered patients across Anna Nagar, T. Nagar, Velachery, and Tambaram
                </span>
              </div>
              <PatientsTable />
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-[#0F172A] tracking-tight flex items-center gap-2">
                    <span>Forwarded Patient Requests</span>
                    <span className="text-xs px-2.5 py-0.5 rounded-full bg-[#FFEDD5] text-[#EA580C] border border-[#FED7AA] font-semibold">
                      Escalations Queue
                    </span>
                  </h2>
                  <p className="text-xs text-[#64748B] mt-0.5">
                    Patients asking for front desk assistance, transfers, or policy-related appointment exceptions
                  </p>
                </div>
              </div>
              <ForwardedRequestsTable />
            </div>
          )}
        </div>

        {/* Clinic Branches & Doctor Rosters */}
        <LocationRoster />
      </main>

      {/* Footer */}
      <footer className="border-t border-[#E2E8F0] bg-white py-6 mt-12">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-[#64748B]">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-[#14B8A6]" />
            <span>{ENV.CLINIC_NAME} Frontdesk Operations Portal</span>
          </div>
          <span>Active Branches: Anna Nagar, T. Nagar, Velachery, Tambaram</span>
        </div>
      </footer>
    </div>
  )
}
