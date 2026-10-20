import React, { useState } from 'react'
import {
  Search,
  RefreshCw,
  Phone,
  Mail,
  Calendar,
  Clock,
  MapPin,
  Stethoscope,
  Inbox,
} from 'lucide-react'
import { Card } from '../../../components/ui/Card'
import { Input } from '../../../components/ui/Input'
import { Button } from '../../../components/ui/Button'
import { StatusBadge } from './StatusBadge'
import { usePatients } from '../queries/frontdeskQueries'
import { formatDateTime, formatPhone } from '../../../lib/utils'

export const PatientsTable: React.FC = () => {
  const [searchQuery, setSearchQuery] = useState('')

  const { data, isLoading, isFetching, refetch } = usePatients(
    searchQuery.trim() || undefined
  )

  const patients = data?.patients || []

  return (
    <div className="space-y-4">
      {/* Control Bar: Search & Refresh */}
      <Card glow="none" className="p-4 sm:p-5">
        <div className="flex flex-col sm:flex-row gap-3 items-center justify-between">
          <div className="w-full sm:max-w-md">
            <Input
              placeholder="Search by patient name, phone, or email..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              leftIcon={<Search className="w-4 h-4" />}
              className="h-10 text-xs"
            />
          </div>

          <div className="flex items-center gap-2 w-full sm:w-auto">
            <Button
              type="button"
              variant="outline"
              size="md"
              className="w-full sm:w-auto h-10 text-xs justify-center"
              onClick={() => refetch()}
              isLoading={isFetching}
              leftIcon={
                <RefreshCw
                  className={`w-3.5 h-3.5 ${isFetching ? 'animate-spin' : ''}`}
                />
              }
            >
              Refresh Patients
            </Button>
          </div>
        </div>
      </Card>

      {/* Main Table Container */}
      <Card glow="none" className="p-0 overflow-hidden border-slate-800">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border-collapse">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-900/80 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                <th className="py-3.5 px-4">Patient Name</th>
                <th className="py-3.5 px-4">Contact Info</th>
                <th className="py-3.5 px-4">Date of Birth</th>
                <th className="py-3.5 px-4">Active Appointment</th>
                <th className="py-3.5 px-4 text-center">Visits</th>
                <th className="py-3.5 px-4">Registered At</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-sans">
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400">
                    <RefreshCw className="w-6 h-6 animate-spin mx-auto text-teal-400 mb-2" />
                    <span>Loading registered patients...</span>
                  </td>
                </tr>
              ) : patients.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="py-14 text-center text-slate-400 space-y-2"
                  >
                    <Inbox className="w-8 h-8 mx-auto text-slate-600 mb-1" />
                    <p className="text-sm font-medium text-slate-300">
                      No registered patients found
                    </p>
                    <p className="text-xs text-slate-500">
                      New patients will automatically appear here once registered.
                    </p>
                  </td>
                </tr>
              ) : (
                patients.map((patient) => {
                  const active = patient.active_appointment
                  return (
                    <tr
                      key={patient.id}
                      className="hover:bg-slate-800/40 transition-colors duration-150 text-slate-200"
                    >
                      {/* Name */}
                      <td className="py-3.5 px-4">
                        <div className="flex items-center gap-2.5">
                          <div className="w-8 h-8 rounded-full bg-teal-500/10 border border-teal-500/20 text-teal-400 flex items-center justify-center font-bold text-xs shrink-0">
                            {patient.full_name.charAt(0).toUpperCase()}
                          </div>
                          <div>
                            <p className="font-semibold text-white text-xs sm:text-sm">
                              {patient.full_name}
                            </p>
                            <span className="text-[10px] text-slate-500 font-mono">
                              ID: {patient.id.slice(0, 8)}
                            </span>
                          </div>
                        </div>
                      </td>

                      {/* Contact */}
                      <td className="py-3.5 px-4">
                        <div className="space-y-0.5 text-xs">
                          <p className="text-slate-300 flex items-center gap-1.5 font-mono">
                            <Phone className="w-3 h-3 text-slate-500 shrink-0" />
                            {patient.phone ? formatPhone(patient.phone) : '—'}
                          </p>
                          {patient.email ? (
                            <p className="text-[11px] text-slate-400 flex items-center gap-1.5">
                              <Mail className="w-3 h-3 text-slate-500 shrink-0" />
                              <span className="truncate max-w-[180px]">
                                {patient.email}
                              </span>
                            </p>
                          ) : null}
                        </div>
                      </td>

                      {/* DOB */}
                      <td className="py-3.5 px-4 text-xs text-slate-300">
                        {patient.date_of_birth ? (
                          <div className="flex items-center gap-1.5">
                            <Calendar className="w-3.5 h-3.5 text-teal-400/80" />
                            <span>{patient.date_of_birth}</span>
                          </div>
                        ) : (
                          <span className="text-slate-500">—</span>
                        )}
                      </td>

                      {/* Active Appointment Status */}
                      <td className="py-3.5 px-4">
                        {active ? (
                          <div className="p-2 rounded-lg bg-slate-900/90 border border-slate-800 space-y-1 text-xs max-w-xs">
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-medium text-white flex items-center gap-1 truncate">
                                <Stethoscope className="w-3 h-3 text-teal-400 shrink-0" />
                                {active.doctor_name}
                              </span>
                              <StatusBadge status={active.status} />
                            </div>
                            <div className="flex items-center gap-1.5 text-[11px] text-slate-400">
                              <MapPin className="w-3 h-3 text-slate-500 shrink-0" />
                              <span className="truncate">{active.location_name}</span>
                            </div>
                            <div className="flex items-center gap-1.5 text-[11px] text-teal-400/90 font-mono">
                              <Clock className="w-3 h-3 shrink-0" />
                              <span>{formatDateTime(active.start_time)}</span>
                            </div>
                          </div>
                        ) : (
                          <span className="text-xs text-slate-500 italic">
                            No active booking
                          </span>
                        )}
                      </td>

                      {/* Total Visits */}
                      <td className="py-3.5 px-4 text-center">
                        <span className="inline-flex items-center justify-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-800 text-slate-300 border border-slate-700">
                          {patient.total_appointments}
                        </span>
                      </td>

                      {/* Registered Date */}
                      <td className="py-3.5 px-4 text-xs text-slate-400">
                        {patient.created_at
                          ? formatDateTime(patient.created_at)
                          : '—'}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Footer info bar */}
        <div className="py-3 px-4 bg-slate-900/60 border-t border-slate-800 text-xs text-slate-400 flex items-center justify-between">
          <span>Showing {patients.length} registered patient profiles</span>
          <span className="text-[11px] text-teal-400/80">
            Auto-refresh active (5s interval)
          </span>
        </div>
      </Card>
    </div>
  )
}
