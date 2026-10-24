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
import { StatusBadge } from './StatusBadge'
import { usePatients } from '../queries/frontdeskQueries'
import { formatDateTime, formatPhone } from '../../../lib/utils'
import { RefreshButton } from './RefreshButton'

export const PatientsTable: React.FC = () => {
  const [searchQuery, setSearchQuery] = useState('')

  const { data, isLoading, refetch, dataUpdatedAt } = usePatients(
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
              leftIcon={<Search className="w-4 h-4 text-[#64748B]" />}
              className="h-10 text-xs"
            />
          </div>

          <div className="flex items-center gap-2 w-full sm:w-auto">
            <RefreshButton
              label="Refresh Patients"
              className="w-full sm:w-auto"
              updatedAt={dataUpdatedAt}
              onRefresh={() => refetch()}
            />
          </div>
        </div>
      </Card>

      {/* Main Table Container */}
      <Card glow="none" className="p-0 overflow-hidden border-[#E2E8F0]">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border-collapse">
            <thead>
              <tr className="border-b border-[#E2E8F0] bg-[#F1F5F9] text-[11px] font-semibold uppercase tracking-wider text-[#475569]">
                <th className="py-3.5 px-4">Patient Name</th>
                <th className="py-3.5 px-4">Contact Info</th>
                <th className="py-3.5 px-4">Date of Birth</th>
                <th className="py-3.5 px-4">Active Appointment</th>
                <th className="py-3.5 px-4">Registered At</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E2E8F0] font-sans">
              {isLoading ? (
                <tr>
                  <td colSpan={5} className="py-12 text-center text-[#64748B]">
                    <RefreshCw className="w-6 h-6 animate-spin mx-auto text-[#14B8A6] mb-2" />
                    <span>Loading registered patients...</span>
                  </td>
                </tr>
              ) : patients.length === 0 ? (
                <tr>
                  <td
                    colSpan={5}
                    className="py-14 text-center text-[#64748B] space-y-2"
                  >
                    <Inbox className="w-8 h-8 mx-auto text-[#94A3B8] mb-1" />
                    <p className="text-sm font-semibold text-[#0F172A]">
                      No registered patients found
                    </p>
                    <p className="text-xs text-[#64748B]">
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
                      className="hover:bg-[#F8FAFC] transition-colors duration-150 text-[#0F172A]"
                    >
                      {/* Name */}
                      <td className="py-3.5 px-4">
                        <div className="flex items-center gap-2.5">
                          <div className="w-8 h-8 rounded-full bg-[#CCFBF1] border border-[#99F6E4] text-[#0D9488] flex items-center justify-center font-bold text-xs shrink-0">
                            {patient.full_name.charAt(0).toUpperCase()}
                          </div>
                          <div>
                            <p className="font-semibold text-[#0F172A] text-xs sm:text-sm">
                              {patient.full_name}
                            </p>
                            <span className="text-[10px] text-[#64748B] font-mono">
                              ID: {patient.id.slice(0, 8)}
                            </span>
                          </div>
                        </div>
                      </td>

                      {/* Contact */}
                      <td className="py-3.5 px-4">
                        <div className="space-y-0.5 text-xs">
                          <p className="text-[#0F172A] flex items-center gap-1.5 font-mono">
                            <Phone className="w-3 h-3 text-[#64748B] shrink-0" />
                            {patient.phone ? formatPhone(patient.phone) : '—'}
                          </p>
                          {patient.email ? (
                            <p className="text-[11px] text-[#475569] flex items-center gap-1.5">
                              <Mail className="w-3 h-3 text-[#64748B] shrink-0" />
                              <span className="truncate max-w-[180px]">
                                {patient.email}
                              </span>
                            </p>
                          ) : null}
                        </div>
                      </td>

                      {/* DOB */}
                      <td className="py-3.5 px-4 text-xs text-[#0F172A]">
                        {patient.date_of_birth ? (
                          <div className="flex items-center gap-1.5">
                            <Calendar className="w-3.5 h-3.5 text-[#0D9488]" />
                            <span>{patient.date_of_birth}</span>
                          </div>
                        ) : (
                          <span className="text-[#64748B]">—</span>
                        )}
                      </td>

                      {/* Active Appointment Status */}
                      <td className="py-3.5 px-4">
                        {active ? (
                          <div className="p-2 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] space-y-1 text-xs max-w-xs">
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-medium text-[#0F172A] flex items-center gap-1 truncate">
                                <Stethoscope className="w-3.5 h-3.5 text-[#0D9488] shrink-0" />
                                {active.doctor_name}
                              </span>
                              <StatusBadge status={active.status} />
                            </div>
                            <div className="flex items-center gap-1.5 text-[11px] text-[#475569]">
                              <MapPin className="w-3.5 h-3.5 text-[#64748B] shrink-0" />
                              <span className="truncate">{active.location_name}</span>
                            </div>
                            <div className="flex items-center gap-1.5 text-[11px] text-[#0D9488] font-mono">
                              <Clock className="w-3.5 h-3.5 shrink-0" />
                              <span>{formatDateTime(active.start_time)}</span>
                            </div>
                          </div>
                        ) : (
                          <span className="text-xs text-[#64748B] italic">
                            No active booking
                          </span>
                        )}
                      </td>

                      {/* Registered Date */}
                      <td className="py-3.5 px-4 text-xs text-[#64748B]">
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
        <div className="py-3 px-4 bg-[#F1F5F9] border-t border-[#E2E8F0] text-xs text-[#475569] flex items-center justify-between">
          <span>Showing {patients.length} registered patient profiles</span>
          <span className="text-[11px] text-[#0D9488] font-medium">
            Auto-refresh active (5s interval)
          </span>
        </div>
      </Card>
    </div>
  )
}
