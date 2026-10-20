import React, { useState } from 'react'
import {
  Search,
  RefreshCw,
  Calendar,
  Clock,
  Phone,
  User,
  MapPin,
  Stethoscope,
  Inbox,
} from 'lucide-react'
import { Card } from '../../../components/ui/Card'
import { Input } from '../../../components/ui/Input'
import { Select } from '../../../components/ui/Select'
import { Button } from '../../../components/ui/Button'
import { StatusBadge } from './StatusBadge'
import { useAppointments } from '../queries/frontdeskQueries'
import {
  APPOINTMENT_STATUS_FILTERS,
  CLINIC_BRANCHES,
} from '../../../config/constants'
import { formatDateTime, formatPhone } from '../../../lib/utils'

export const AppointmentsTable: React.FC = () => {
  const [statusFilter, setStatusFilter] = useState('all')
  const [locationFilter, setLocationFilter] = useState('all')
  const [searchQuery, setSearchQuery] = useState('')

  const {
    data,
    isLoading,
    isFetching,
    refetch,
  } = useAppointments({
    status: statusFilter !== 'all' ? statusFilter : undefined,
    location: locationFilter !== 'all' ? locationFilter : undefined,
    search: searchQuery.trim() || undefined,
  })

  const appointments = data?.appointments || []

  return (
    <div className="space-y-4">
      {/* Control Bar: Filters & Search */}
      <Card glow="none" className="p-4 sm:p-5">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 items-end">
          <Input
            placeholder="Search patient, phone, or doctor..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            leftIcon={<Search className="w-4 h-4" />}
            className="h-10 text-xs"
          />

          <Select
            options={APPOINTMENT_STATUS_FILTERS}
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="h-10 text-xs"
          />

          <Select
            options={CLINIC_BRANCHES}
            value={locationFilter}
            onChange={(e) => setLocationFilter(e.target.value)}
            className="h-10 text-xs"
          />

          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="md"
              className="w-full h-10 text-xs justify-center"
              onClick={() => refetch()}
              isLoading={isFetching}
              leftIcon={<RefreshCw className={`w-3.5 h-3.5 ${isFetching ? 'animate-spin' : ''}`} />}
            >
              Refresh Table
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
                <th className="py-3.5 px-4">Patient</th>
                <th className="py-3.5 px-4">Doctor & Specialty</th>
                <th className="py-3.5 px-4">Branch Location</th>
                <th className="py-3.5 px-4">Appointment Slot</th>
                <th className="py-3.5 px-4">Status</th>
                <th className="py-3.5 px-4">Booked At</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-sans">
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400">
                    <RefreshCw className="w-6 h-6 animate-spin mx-auto text-teal-400 mb-2" />
                    <span>Loading appointments...</span>
                  </td>
                </tr>
              ) : appointments.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-14 text-center text-slate-400 space-y-2">
                    <Inbox className="w-8 h-8 mx-auto text-slate-600 mb-1" />
                    <p className="text-sm font-medium text-slate-300">No appointments found</p>
                    <p className="text-xs text-slate-500">
                      Try adjusting the search query, status, or branch filters.
                    </p>
                  </td>
                </tr>
              ) : (
                appointments.map((appt) => (
                  <tr
                    key={appt.id}
                    className="hover:bg-slate-800/40 transition-colors duration-150 text-slate-200"
                  >
                    {/* Patient info */}
                    <td className="py-3.5 px-4">
                      <div className="flex items-center gap-2.5">
                        <div className="w-8 h-8 rounded-full bg-teal-500/10 border border-teal-500/20 text-teal-400 flex items-center justify-center shrink-0">
                          <User className="w-4 h-4" />
                        </div>
                        <div>
                          <p className="font-semibold text-white text-xs sm:text-sm">
                            {appt.patient_name}
                          </p>
                          <p className="text-[11px] text-slate-400 flex items-center gap-1 font-mono">
                            <Phone className="w-3 h-3 text-slate-500" />
                            {formatPhone(appt.patient_phone)}
                          </p>
                        </div>
                      </div>
                    </td>

                    {/* Doctor info */}
                    <td className="py-3.5 px-4">
                      <div className="space-y-0.5">
                        <p className="font-medium text-slate-200 text-xs sm:text-sm flex items-center gap-1.5">
                          <Stethoscope className="w-3.5 h-3.5 text-teal-400 shrink-0" />
                          {appt.doctor_name}
                        </p>
                        <p className="text-xs text-slate-400 pl-5">{appt.specialty}</p>
                      </div>
                    </td>

                    {/* Location */}
                    <td className="py-3.5 px-4">
                      <div className="space-y-0.5">
                        <p className="font-medium text-slate-200 text-xs sm:text-sm flex items-center gap-1.5">
                          <MapPin className="w-3.5 h-3.5 text-teal-400 shrink-0" />
                          {appt.location_name}
                        </p>
                        {appt.location_address && (
                          <p className="text-[11px] text-slate-400 truncate max-w-[200px] pl-5">
                            {appt.location_address}
                          </p>
                        )}
                      </div>
                    </td>

                    {/* Slot */}
                    <td className="py-3.5 px-4">
                      <div className="space-y-0.5 text-xs">
                        <p className="font-medium text-slate-200 flex items-center gap-1.5">
                          <Calendar className="w-3.5 h-3.5 text-teal-400" />
                          {formatDateTime(appt.start_time)}
                        </p>
                        {appt.end_time && (
                          <p className="text-[11px] text-slate-400 flex items-center gap-1 pl-5">
                            <Clock className="w-3 h-3 text-slate-500" />
                            to {new Date(appt.end_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                          </p>
                        )}
                      </div>
                    </td>

                    {/* Status */}
                    <td className="py-3.5 px-4">
                      <StatusBadge status={appt.status} />
                    </td>

                    {/* Created at */}
                    <td className="py-3.5 px-4 text-xs text-slate-400">
                      {formatDateTime(appt.created_at)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Footer info bar */}
        <div className="py-3 px-4 bg-slate-900/60 border-t border-slate-800 text-xs text-slate-400 flex items-center justify-between">
          <span>Showing {appointments.length} appointment records</span>
          <span className="text-[11px] text-teal-400/80">Auto-refresh active (5s interval)</span>
        </div>
      </Card>
    </div>
  )
}
