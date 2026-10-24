import React, { useState, useMemo, useEffect } from 'react'
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
  X,
  RotateCcw,
  ArrowDownUp,
} from 'lucide-react'
import { Card } from '../../../components/ui/Card'
import { Input } from '../../../components/ui/Input'
import { Select } from '../../../components/ui/Select'
import { Button } from '../../../components/ui/Button'
import { StatusBadge } from './StatusBadge'
import { RefreshButton } from './RefreshButton'
import { useAppointments, useAppointmentTypes, useClinicLocations } from '../queries/frontdeskQueries'
import { ConfirmationBadge } from './ConfirmationBadge'
import {
  APPOINTMENT_SORT_OPTIONS,
  APPOINTMENT_STATUS_FILTERS,
  CHANNEL_FILTERS,
  CONFIRMATION_STATUS_FILTERS,
  CLINIC_BRANCHES,
} from '../../../config/constants'
import { formatClockIST, formatDateTime, formatPhone } from '../../../lib/utils'

export const AppointmentsTable: React.FC = () => {
  const [statusFilter, setStatusFilter] = useState('all')
  const [locationFilter, setLocationFilter] = useState('all')
  const [channelFilter, setChannelFilter] = useState('all')
  const [providerFilter, setProviderFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [confirmationFilter, setConfirmationFilter] = useState('all')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [sortBy, setSortBy] = useState('created_at')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')

  // Debounce search query to avoid stuttering requests
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery.trim())
    }, 250)
    return () => clearTimeout(timer)
  }, [searchQuery])

  const { data: locationsData } = useClinicLocations()
  const { data: appointmentTypes } = useAppointmentTypes()

  const providerOptions = useMemo(
    () => [
      { id: 'all', label: 'All Doctors' },
      ...Array.from(
        new Set((locationsData?.locations ?? []).flatMap((loc) => loc.doctors.map((doc) => doc.full_name)))
      )
        .sort()
        .map((name) => ({ id: name, label: name })),
    ],
    [locationsData]
  )
  const typeOptions = useMemo(
    () => [{ id: 'all', label: 'All Appointment Types' }, ...(appointmentTypes ?? []).map((n) => ({ id: n, label: n }))],
    [appointmentTypes]
  )

  // Dynamic branch list from DB locations or fallback to constants
  const branchOptions = useMemo(() => {
    if (!locationsData?.locations?.length) {
      return CLINIC_BRANCHES
    }
    return [
      { id: 'all', label: 'All Branches' },
      ...locationsData.locations.map((loc) => ({
        id: loc.name.replace(/\s+Branch$/i, '').trim(),
        label: loc.name,
      })),
    ]
  }, [locationsData])

  const {
    data,
    isLoading,
    refetch,
    dataUpdatedAt,
  } = useAppointments({
    status: statusFilter !== 'all' ? statusFilter : undefined,
    location: locationFilter !== 'all' ? locationFilter : undefined,
    search: debouncedSearch || undefined,
    channel: channelFilter !== 'all' ? channelFilter : undefined,
    provider: providerFilter !== 'all' ? providerFilter : undefined,
    appointment_type: typeFilter !== 'all' ? typeFilter : undefined,
    confirmation_status: confirmationFilter !== 'all' ? confirmationFilter : undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    sort: sortBy,
    order: sortOrder,
  })

  const rawAppointments = data?.appointments || []

  // Client-side filtering ensures instant response and catches any fields
  const appointments = useMemo(() => {
    let list = rawAppointments

    // Instant filter while typing
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase()
      list = list.filter((a) => {
        return (
          a.patient_name.toLowerCase().includes(q) ||
          a.patient_phone.toLowerCase().includes(q) ||
          a.doctor_name.toLowerCase().includes(q) ||
          a.specialty.toLowerCase().includes(q) ||
          a.location_name.toLowerCase().includes(q) ||
          (a.location_address && a.location_address.toLowerCase().includes(q)) ||
          a.status.toLowerCase().includes(q)
        )
      })
    }

    if (statusFilter !== 'all') {
      list = list.filter((a) => a.status.toLowerCase() === statusFilter.toLowerCase())
    }

    if (locationFilter !== 'all') {
      const locLower = locationFilter.toLowerCase()
      list = list.filter((a) => a.location_name.toLowerCase().includes(locLower))
    }

    return list
  }, [rawAppointments, searchQuery, statusFilter, locationFilter])

  const isFiltered =
    statusFilter !== 'all' ||
    locationFilter !== 'all' ||
    channelFilter !== 'all' ||
    providerFilter !== 'all' ||
    typeFilter !== 'all' ||
    confirmationFilter !== 'all' ||
    dateFrom !== '' ||
    dateTo !== '' ||
    searchQuery.trim() !== ''

  const handleResetFilters = () => {
    setStatusFilter('all')
    setLocationFilter('all')
    setChannelFilter('all')
    setProviderFilter('all')
    setTypeFilter('all')
    setConfirmationFilter('all')
    setDateFrom('')
    setDateTo('')
    setSearchQuery('')
    setDebouncedSearch('')
  }

  return (
    <div className="space-y-4">
      {/* Control Bar: Filters & Search */}
      <Card glow="none" className="p-4 sm:p-5">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 items-end">
          <div className="relative">
            <Input
              placeholder="Search patient, phone, or doctor..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              leftIcon={<Search className="w-4 h-4 text-[#64748B]" />}
              className="h-10 text-xs pr-8"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[#94A3B8] hover:text-[#0F172A] p-0.5"
                title="Clear search"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          <Select
            options={APPOINTMENT_STATUS_FILTERS}
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="h-10 text-xs"
          />

          <Select
            options={branchOptions}
            value={locationFilter}
            onChange={(e) => setLocationFilter(e.target.value)}
            className="h-10 text-xs"
          />

          <div className="flex items-center gap-2">
            <RefreshButton
              label="Refresh Table"
              className="w-full"
              updatedAt={dataUpdatedAt}
              onRefresh={() => refetch()}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 items-end mt-3">
          <Select
            options={providerOptions}
            value={providerFilter}
            onChange={(e) => setProviderFilter(e.target.value)}
            className="h-10 text-xs"
          />
          <Select
            options={typeOptions}
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="h-10 text-xs"
          />
          <Select
            options={CONFIRMATION_STATUS_FILTERS}
            value={confirmationFilter}
            onChange={(e) => setConfirmationFilter(e.target.value)}
            className="h-10 text-xs"
          />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 items-end mt-3">
          <Select
            options={CHANNEL_FILTERS}
            value={channelFilter}
            onChange={(e) => setChannelFilter(e.target.value)}
            className="h-10 text-xs"
          />
          <Input
            type="date"
            label="Appointment from"
            value={dateFrom}
            max={dateTo || undefined}
            onChange={(e) => setDateFrom(e.target.value)}
            className="h-10 text-xs"
          />
          <Input
            type="date"
            label="Appointment to"
            value={dateTo}
            min={dateFrom || undefined}
            onChange={(e) => setDateTo(e.target.value)}
            className="h-10 text-xs"
          />
          <Select
            options={APPOINTMENT_SORT_OPTIONS}
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            className="h-10 text-xs"
          />
          <Button
            type="button"
            variant="outline"
            size="md"
            className="w-full h-10 text-xs justify-center"
            onClick={() => setSortOrder((o) => (o === 'asc' ? 'desc' : 'asc'))}
            leftIcon={<ArrowDownUp className="w-3.5 h-3.5" />}
          >
            {sortOrder === 'asc' ? 'Oldest / A-Z first' : 'Newest / Z-A first'}
          </Button>
        </div>

        {isFiltered && (
          <div className="flex flex-wrap items-center justify-between gap-2 pt-3 mt-3 border-t border-[#E2E8F0] text-xs">
            <div className="flex flex-wrap items-center gap-2 text-[#475569]">
              <span className="font-semibold text-[#0F172A]">Active Filters:</span>
              {statusFilter !== 'all' && (
                <span className="px-2 py-0.5 rounded-md bg-[#CCFBF1] text-[#0D9488] font-medium border border-[#99F6E4] capitalize">
                  Status: {statusFilter}
                </span>
              )}
              {locationFilter !== 'all' && (
                <span className="px-2 py-0.5 rounded-md bg-[#E0F2FE] text-[#0284C7] font-medium border border-[#BAE6FD]">
                  Branch: {locationFilter}
                </span>
              )}
              {searchQuery.trim() && (
                <span className="px-2 py-0.5 rounded-md bg-[#F1F5F9] text-[#334155] font-medium border border-[#CBD5E1]">
                  Query: &quot;{searchQuery.trim()}&quot;
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={handleResetFilters}
              className="text-[#E11D48] hover:text-[#BE123C] font-semibold text-xs flex items-center gap-1 cursor-pointer transition-colors"
            >
              <RotateCcw className="w-3 h-3" />
              Reset Filters
            </button>
          </div>
        )}
      </Card>

      {/* Main Table Container */}
      <Card glow="none" className="p-0 overflow-hidden border-[#E2E8F0]">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border-collapse">
            <thead>
              <tr className="border-b border-[#E2E8F0] bg-[#F1F5F9] text-[11px] font-semibold uppercase tracking-wider text-[#475569]">
                <th className="py-3.5 px-4">Patient</th>
                <th className="py-3.5 px-4">Doctor & Specialty</th>
                <th className="py-3.5 px-4">Branch Location</th>
                <th className="py-3.5 px-4">Appointment Slot</th>
                <th className="py-3.5 px-4">Status</th>
                <th className="py-3.5 px-4">Booked At</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E2E8F0] font-sans">
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-[#64748B]">
                    <RefreshCw className="w-6 h-6 animate-spin mx-auto text-[#14B8A6] mb-2" />
                    <span>Loading appointments...</span>
                  </td>
                </tr>
              ) : appointments.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-14 text-center text-[#64748B] space-y-2">
                    <Inbox className="w-8 h-8 mx-auto text-[#94A3B8] mb-1" />
                    <p className="text-sm font-semibold text-[#0F172A]">No appointments found</p>
                    <p className="text-xs text-[#64748B]">
                      {isFiltered
                        ? 'Try adjusting or clearing your active filters.'
                        : 'No appointment records available.'}
                    </p>
                    {isFiltered && (
                      <button
                        type="button"
                        onClick={handleResetFilters}
                        className="inline-flex items-center gap-1 text-xs font-semibold text-[#0D9488] hover:underline pt-2 cursor-pointer"
                      >
                        <RotateCcw className="w-3 h-3" />
                        Reset All Filters
                      </button>
                    )}
                  </td>
                </tr>
              ) : (
                appointments.map((appt) => (
                  <tr
                    key={appt.id}
                    className="hover:bg-[#F8FAFC] transition-colors duration-150 text-[#0F172A]"
                  >
                    {/* Patient info */}
                    <td className="py-3.5 px-4">
                      <div className="flex items-center gap-2.5">
                        <div className="w-8 h-8 rounded-full bg-[#CCFBF1] border border-[#99F6E4] text-[#0D9488] flex items-center justify-center shrink-0">
                          <User className="w-4 h-4" />
                        </div>
                        <div>
                          <p className="font-semibold text-[#0F172A] text-xs sm:text-sm">
                            {appt.patient_name}
                          </p>
                          <p className="text-[11px] text-[#475569] flex items-center gap-1 font-mono">
                            <Phone className="w-3 h-3 text-[#64748B]" />
                            {formatPhone(appt.patient_phone)}
                          </p>
                        </div>
                      </div>
                    </td>

                    {/* Doctor info */}
                    <td className="py-3.5 px-4">
                      <div className="space-y-0.5">
                        <p className="font-medium text-[#0F172A] text-xs sm:text-sm flex items-center gap-1.5">
                          <Stethoscope className="w-3.5 h-3.5 text-[#0D9488] shrink-0" />
                          {appt.doctor_name}
                        </p>
                        <p className="text-xs text-[#475569] pl-5">{appt.specialty}</p>
                      </div>
                    </td>

                    {/* Location */}
                    <td className="py-3.5 px-4">
                      <div className="space-y-0.5">
                        <p className="font-medium text-[#0F172A] text-xs sm:text-sm flex items-center gap-1.5">
                          <MapPin className="w-3.5 h-3.5 text-[#0D9488] shrink-0" />
                          {appt.location_name}
                        </p>
                        {appt.location_address && (
                          <p className="text-[11px] text-[#475569] truncate max-w-[200px] pl-5">
                            {appt.location_address}
                          </p>
                        )}
                      </div>
                    </td>

                    {/* Slot */}
                    <td className="py-3.5 px-4">
                      <div className="space-y-0.5 text-xs">
                        <p className="font-medium text-[#0F172A] flex items-center gap-1.5">
                          <Calendar className="w-3.5 h-3.5 text-[#0D9488]" />
                          {formatDateTime(appt.start_time)}
                        </p>
                        {appt.end_time && (
                          <p className="text-[11px] text-[#475569] flex items-center gap-1 pl-5">
                            <Clock className="w-3 h-3 text-[#64748B]" />
                            to {formatClockIST(appt.end_time)}
                          </p>
                        )}
                      </div>
                    </td>

                    {/* Status */}
                    <td className="py-3.5 px-4">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <StatusBadge status={appt.status} />
                        <ConfirmationBadge status={appt.confirmation_status} />
                      </div>
                      {(appt.appointment_type || appt.channel) && (
                        <p className="text-[11px] text-[#64748B] mt-1">
                          {[appt.appointment_type, appt.channel?.replace('_', ' ')].filter(Boolean).join(' · ')}
                        </p>
                      )}
                    </td>

                    {/* Created at */}
                    <td className="py-3.5 px-4 text-xs text-[#64748B]">
                      {formatDateTime(appt.created_at)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Footer info bar */}
        <div className="py-3 px-4 bg-[#F1F5F9] border-t border-[#E2E8F0] text-xs text-[#475569] flex items-center justify-between">
          <span>Showing {appointments.length} appointment records</span>
          <span className="text-[11px] text-[#0D9488] font-medium">Auto-refresh active (5s interval)</span>
        </div>
      </Card>
    </div>
  )
}
