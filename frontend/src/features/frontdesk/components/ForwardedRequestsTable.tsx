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
  AlertTriangle,
  MessageSquare,
  Mic,
  PhoneCall,
  CheckCircle2,
  X,
  FileText,
  User,
  ShieldCheck,
  ArrowUpRight,
} from 'lucide-react'
import { Card } from '../../../components/ui/Card'
import { Input } from '../../../components/ui/Input'
import { Button } from '../../../components/ui/Button'
import { Badge } from '../../../components/ui/Badge'
import {
  useForwardedRequests,
  useUpdateForwardedRequest,
} from '../queries/frontdeskQueries'
import { useQueryClient } from '@tanstack/react-query'
import type { ForwardedRequestRecord } from '../../../types'
import { formatDateTime, formatPhone } from '../../../lib/utils'

export const ForwardedRequestsTable: React.FC = () => {
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'pending' | 'contacted' | 'resolved'>('all')
  const [selectedRequest, setSelectedRequest] = useState<ForwardedRequestRecord | null>(null)
  const [staffNote, setStaffNote] = useState('')
  const [isManualRefreshing, setIsManualRefreshing] = useState(false)
  const queryClient = useQueryClient()

  const { data, isLoading, refetch } = useForwardedRequests({
    status: statusFilter === 'all' ? undefined : statusFilter,
    search: searchQuery.trim() || undefined,
  })

  const handleRefresh = async () => {
    setIsManualRefreshing(true)
    try {
      await Promise.all([
        refetch(),
        queryClient.invalidateQueries({ queryKey: ['dashboard', 'forwarded_requests'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard', 'stats'] }),
      ])
    } finally {
      setTimeout(() => setIsManualRefreshing(false), 500)
    }
  }

  const updateMutation = useUpdateForwardedRequest()

  const requests = data?.forwarded_requests || []
  const pendingCount = data?.pending_count || 0

  const handleUpdateStatus = (
    req: ForwardedRequestRecord,
    newStatus: 'pending' | 'contacted' | 'resolved',
    note?: string
  ) => {
    updateMutation.mutate({
      id: req.id,
      data: { status: newStatus, notes: note ?? req.notes ?? undefined },
    })
  }

  const getChannelBadge = (channel: string) => {
    switch (channel.toLowerCase()) {
      case 'chat':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#CCFBF1] text-[#0D9488] border border-[#99F6E4]">
            <MessageSquare className="w-3 h-3 text-[#0D9488]" />
            <span>Web Chat</span>
          </span>
        )
      case 'voice':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#E0E7FF] text-[#6366F1] border border-[#C7D2FE]">
            <Mic className="w-3 h-3 text-[#6366F1]" />
            <span>Voice Assistant</span>
          </span>
        )
      case 'outbound_call':
      case 'call':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#E0F2FE] text-[#0284C7] border border-[#BAE6FD]">
            <PhoneCall className="w-3 h-3 text-[#0284C7]" />
            <span>Outbound Call</span>
          </span>
        )
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#F1F5F9] text-[#475569] border border-[#E2E8F0]">
            {channel}
          </span>
        )
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'pending':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-[#FFEDD5] text-[#EA580C] border border-[#FED7AA] animate-pulse">
            <span className="w-2 h-2 rounded-full bg-[#EA580C]" />
            <span>Needs Action</span>
          </span>
        )
      case 'contacted':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-[#FEF3C7] text-[#B45309] border border-[#FDE68A]">
            <span className="w-2 h-2 rounded-full bg-[#B45309]" />
            <span>Contacted</span>
          </span>
        )
      case 'resolved':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-[#D1FAE5] text-[#059669] border border-[#A7F3D0]">
            <CheckCircle2 className="w-3 h-3 text-[#059669]" />
            <span>Resolved</span>
          </span>
        )
      default:
        return (
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-[#F1F5F9] text-[#475569]">
            {status}
          </span>
        )
    }
  }

  return (
    <div className="space-y-4">
      {/* Alert Header if Pending Escalations Exist */}
      {pendingCount > 0 && (
        <div className="p-4 rounded-2xl bg-[#FFEDD5] border border-[#FED7AA] shadow-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-white border border-[#FED7AA] flex items-center justify-center text-[#EA580C] shrink-0 shadow-sm">
              <AlertTriangle className="w-5 h-5 text-[#EA580C] animate-bounce" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-[#9A3412] flex items-center gap-2">
                <span>{pendingCount} Patient{pendingCount > 1 ? 's' : ''} Forwarded to Front Desk</span>
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-[#EA580C] text-white font-bold">
                  Immediate Follow-up
                </span>
              </h3>
              <p className="text-xs text-[#C2410C] mt-0.5">
                Patients who requested a human representative or ran into appointment scheduling constraints.
              </p>
            </div>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setStatusFilter('pending')}
            className="text-xs border-[#FED7AA] text-[#EA580C] hover:bg-white bg-white/80 shadow-sm"
          >
            Show Pending Only
          </Button>
        </div>
      )}

      {/* Control Bar: Search & Status Filters */}
      <Card glow="none" className="p-4 sm:p-5">
        <div className="flex flex-col lg:flex-row gap-4 items-center justify-between">
          <div className="w-full lg:max-w-md">
            <Input
              placeholder="Search by patient name, phone, doctor, or reason..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              leftIcon={<Search className="w-4 h-4 text-[#64748B]" />}
              className="h-10 text-xs"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2 w-full lg:w-auto">
            {/* Filter pills */}
            <div className="flex items-center gap-1 p-1 bg-[#F1F5F9] border border-[#E2E8F0] rounded-xl">
              {(['all', 'pending', 'contacted', 'resolved'] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setStatusFilter(s)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold capitalize transition-all cursor-pointer ${
                    statusFilter === s
                      ? 'bg-[#0F766E] text-white shadow-sm'
                      : 'text-[#475569] hover:text-[#0F172A]'
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>

            <Button
              type="button"
              variant="outline"
              size="md"
              className="h-10 text-xs justify-center"
              onClick={handleRefresh}
              disabled={isManualRefreshing}
              leftIcon={
                <RefreshCw
                  className={`w-3.5 h-3.5 ${isManualRefreshing ? 'animate-spin' : ''}`}
                />
              }
            >
              {isManualRefreshing ? 'Refreshing...' : 'Refresh'}
            </Button>
          </div>
        </div>
      </Card>

      {/* Main Table Container */}
      <Card glow="none" className="p-0 overflow-hidden border-[#E2E8F0]">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border-collapse">
            <thead>
              <tr className="border-b border-[#E2E8F0] bg-[#F1F5F9] text-[11px] font-semibold uppercase tracking-wider text-[#475569]">
                <th className="py-3.5 px-4">Patient Information</th>
                <th className="py-3.5 px-4">Active Appointment</th>
                <th className="py-3.5 px-4">Escalation Reason & Channel</th>
                <th className="py-3.5 px-4">Forwarded Time</th>
                <th className="py-3.5 px-4">Status</th>
                <th className="py-3.5 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E2E8F0] font-sans">
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-[#64748B]">
                    <RefreshCw className="w-6 h-6 animate-spin mx-auto text-[#14B8A6] mb-2" />
                    <span>Loading forwarded patient requests...</span>
                  </td>
                </tr>
              ) : requests.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="py-14 text-center text-[#64748B] space-y-2"
                  >
                    <CheckCircle2 className="w-10 h-10 mx-auto text-[#059669]/60" />
                    <p className="text-sm font-semibold text-[#0F172A]">
                      No Forwarded Requests Found
                    </p>
                    <p className="text-xs text-[#64748B] max-w-sm mx-auto">
                      All patient requests are actively handled by the clinic AI or marked resolved.
                    </p>
                  </td>
                </tr>
              ) : (
                requests.map((req) => (
                  <tr
                    key={req.id}
                    className="hover:bg-[#F8FAFC] transition-colors group text-[#0F172A]"
                  >
                    {/* Patient Information */}
                    <td className="py-4 px-4 align-top">
                      <div className="space-y-1.5">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-[#0F172A] text-sm">
                            {req.patient_name}
                          </span>
                          {!req.identity_verified && (
                            <span className="inline-flex items-center rounded bg-[#FEF3C7] px-1.5 py-0.5 text-[10px] text-[#92400E] border border-[#FDE68A]">
                              Unverified details
                            </span>
                          )}
                          {req.patient_dob && (
                            <span className="inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded bg-[#D1FAE5] text-[#059669] border border-[#A7F3D0]">
                              <ShieldCheck className="w-3 h-3 text-[#059669]" />
                              DOB: {req.patient_dob}
                            </span>
                          )}
                        </div>

                        {req.patient_phone && req.patient_phone !== '-' && (
                          <div className="flex items-center gap-2 text-xs">
                            <a
                              href={`tel:${req.patient_phone}`}
                              className="inline-flex items-center gap-1.5 text-[#0D9488] hover:text-[#0F766E] font-mono transition-colors font-medium"
                              title="Click to Call Patient"
                            >
                              <Phone className="w-3.5 h-3.5" />
                              <span>{formatPhone(req.patient_phone)}</span>
                              <ArrowUpRight className="w-3 h-3 opacity-60" />
                            </a>
                          </div>
                        )}

                        {req.patient_email && (
                          <div className="flex items-center gap-1.5 text-xs text-[#475569]">
                            <Mail className="w-3 h-3 text-[#64748B]" />
                            <span className="truncate max-w-[180px]">
                              {req.patient_email}
                            </span>
                          </div>
                        )}
                        {req.callback_contact_unavailable && (
                          <div className="text-xs text-[#B45309]">
                            No callback contact provided
                          </div>
                        )}
                        {req.awaiting_handoff_contact && (
                          <div className="text-xs text-[#B45309]">
                            Waiting for callback details
                          </div>
                        )}
                      </div>
                    </td>

                    {/* Active Appointment on File */}
                    <td className="py-4 px-4 align-top">
                      {req.active_appointment ? (
                        <div className="space-y-1.5 p-2.5 rounded-xl bg-[#F8FAFC] border border-[#E2E8F0] text-xs">
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-semibold text-[#0F172A] flex items-center gap-1.5">
                              <Stethoscope className="w-3.5 h-3.5 text-[#0D9488]" />
                              {req.active_appointment.doctor_name}
                            </span>
                            <span className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-[#CCFBF1] text-[#0D9488] border border-[#99F6E4]">
                              {req.active_appointment.status}
                            </span>
                          </div>

                          <div className="text-[11px] text-[#475569] flex items-center gap-1.5">
                            <MapPin className="w-3 h-3 text-[#64748B]" />
                            <span>{req.active_appointment.location_name}</span>
                          </div>

                          <div className="text-[11px] text-[#0D9488] font-medium flex items-center gap-1.5 font-mono">
                            <Calendar className="w-3 h-3 text-[#0D9488]" />
                            <span>{formatDateTime(req.active_appointment.start_time)}</span>
                          </div>
                        </div>
                      ) : (
                        <span className="text-xs text-[#64748B] italic">
                          No active appointment on record
                        </span>
                      )}
                    </td>

                    {/* Forward Reason & Channel */}
                    <td className="py-4 px-4 align-top">
                      <div className="space-y-2 max-w-xs">
                        <div className="flex items-start gap-1.5 text-xs text-[#EA580C] font-semibold">
                          <AlertTriangle className="w-3.5 h-3.5 text-[#EA580C] shrink-0 mt-0.5" />
                          <span>{req.reason}</span>
                        </div>
                        <div>{getChannelBadge(req.channel)}</div>
                      </div>
                    </td>

                    {/* Forwarded Time */}
                    <td className="py-4 px-4 align-top">
                      <div className="space-y-0.5 text-xs text-[#475569]">
                        <div className="flex items-center gap-1.5 text-[#0F172A] font-medium">
                          <Clock className="w-3.5 h-3.5 text-[#64748B]" />
                          <span>{formatDateTime(req.forwarded_at ?? undefined)}</span>
                        </div>
                        <span className="text-[11px] text-[#64748B]">
                          {req.total_messages} turns recorded
                        </span>
                      </div>
                    </td>

                    {/* Status */}
                    <td className="py-4 px-4 align-top">
                      <div className="space-y-2">
                        {getStatusBadge(req.status)}

                        {/* Status Change Dropdown */}
                        <div className="flex items-center gap-1">
                          {req.status !== 'contacted' && (
                            <button
                              type="button"
                              onClick={() => handleUpdateStatus(req, 'contacted')}
                              className="text-[11px] px-2 py-0.5 rounded bg-[#FEF3C7] text-[#B45309] border border-[#FDE68A] hover:bg-[#FDE68A] transition-colors cursor-pointer font-medium"
                              title="Mark patient as contacted by phone"
                            >
                              Contacted
                            </button>
                          )}
                          {req.status !== 'resolved' ? (
                            <button
                              type="button"
                              onClick={() => handleUpdateStatus(req, 'resolved')}
                              className="text-[11px] px-2 py-0.5 rounded bg-[#D1FAE5] text-[#059669] border border-[#A7F3D0] hover:bg-[#A7F3D0] transition-colors cursor-pointer font-medium"
                              title="Mark request as resolved"
                            >
                              Resolve
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={() => handleUpdateStatus(req, 'pending')}
                              className="text-[11px] px-2 py-0.5 rounded bg-[#F1F5F9] text-[#475569] hover:text-[#0F172A] border border-[#E2E8F0] transition-colors cursor-pointer"
                              title="Re-open request"
                            >
                              Re-open
                            </button>
                          )}
                        </div>
                      </div>
                    </td>

                    {/* Actions */}
                    <td className="py-4 px-4 align-top text-right">
                      <div className="flex flex-col sm:flex-row items-end sm:items-center justify-end gap-2">
                        {req.patient_phone && req.patient_phone !== '-' && (
                          <a
                            href={`tel:${req.patient_phone}`}
                            className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg bg-[#0F766E] text-white font-semibold hover:bg-[#0D9488] transition-colors shadow-sm"
                          >
                            <Phone className="w-3.5 h-3.5" />
                            <span>Call</span>
                          </a>
                        )}

                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            setSelectedRequest(req)
                            setStaffNote(req.notes || '')
                          }}
                          className="text-xs"
                          leftIcon={<FileText className="w-3.5 h-3.5 text-[#0D9488]" />}
                        >
                          Transcript
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Transcript & Escalation Modal */}
      {selectedRequest && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/50 backdrop-blur-sm animate-fadeIn">
          <div className="w-full max-w-2xl bg-white border border-[#E2E8F0] rounded-3xl shadow-[var(--shadow-card)] overflow-hidden flex flex-col max-h-[85vh]">
            {/* Modal Header */}
            <div className="p-5 border-b border-[#E2E8F0] flex items-center justify-between bg-[#F8FAFC]">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-2xl bg-[#CCFBF1] text-[#0D9488] border border-[#99F6E4] flex items-center justify-center shadow-sm">
                  <User className="w-5 h-5 text-[#0D9488]" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-[#0F172A] flex items-center gap-2">
                    <span>{selectedRequest.patient_name}</span>
                    <Badge variant="teal" className="text-[10px]">
                      {selectedRequest.channel}
                    </Badge>
                  </h3>
                  <p className="text-xs text-[#475569] flex items-center gap-2 mt-0.5">
                    <span>Phone: {selectedRequest.patient_phone}</span>
                    <span>•</span>
                    <span>Forwarded: {formatDateTime(selectedRequest.forwarded_at ?? undefined)}</span>
                  </p>
                </div>
              </div>

              <button
                type="button"
                onClick={() => setSelectedRequest(null)}
                className="p-2 rounded-xl text-[#64748B] hover:text-[#0F172A] bg-white border border-[#E2E8F0] hover:bg-[#F1F5F9] transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Body: Active Appointment Summary + Messages */}
            <div className="p-5 space-y-4 overflow-y-auto flex-1">
              {/* Active Appointment Banner */}
              {selectedRequest.active_appointment && (
                <div className="p-3.5 rounded-2xl bg-[#F0FDFA] border border-[#99F6E4] text-xs space-y-1">
                  <div className="flex items-center justify-between font-semibold text-[#0F766E]">
                    <span className="flex items-center gap-1.5">
                      <Stethoscope className="w-4 h-4" />
                      Active Appointment: {selectedRequest.active_appointment.doctor_name}
                    </span>
                    <span className="uppercase text-[10px] px-2 py-0.5 rounded bg-[#D1FAE5] text-[#059669] border border-[#A7F3D0]">
                      {selectedRequest.active_appointment.status}
                    </span>
                  </div>
                  <p className="text-[#475569]">
                    Branch: {selectedRequest.active_appointment.location_name} •{' '}
                    {formatDateTime(selectedRequest.active_appointment.start_time)}
                  </p>
                </div>
              )}

              {/* Escalation Reason */}
              <div className="p-3 rounded-xl bg-[#FFEDD5] border border-[#FED7AA] text-xs text-[#EA580C] flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 text-[#EA580C] shrink-0 mt-0.5" />
                <div>
                  <span className="font-bold text-[#9A3412]">Escalation Trigger: </span>
                  <span className="font-medium text-[#C2410C]">{selectedRequest.reason}</span>
                </div>
              </div>

              {/* Turn-by-Turn Conversation Transcript */}
              <div className="space-y-3 pt-2">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-[#475569]">
                  Full Conversation Transcript ({selectedRequest.messages.length} turns)
                </h4>

                {selectedRequest.messages.length === 0 ? (
                  <p className="text-xs text-[#64748B] italic py-4 text-center">
                    No turn messages were logged for this session.
                  </p>
                ) : (
                  <div className="space-y-2.5 max-h-[300px] overflow-y-auto p-3 rounded-2xl bg-[#F8FAFC] border border-[#E2E8F0]">
                    {selectedRequest.messages.map((m, idx) => (
                      <div
                        key={idx}
                        className={`flex flex-col ${
                          m.role === 'patient' ? 'items-end' : 'items-start'
                        }`}
                      >
                        <div
                          className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-xs leading-relaxed ${
                            m.role === 'patient'
                              ? 'bg-[#0F766E] text-white rounded-tr-none shadow-sm'
                              : 'bg-white text-[#0F172A] border border-[#E2E8F0] rounded-tl-none shadow-sm'
                          }`}
                        >
                          <div className="text-[10px] opacity-70 mb-0.5 font-semibold">
                            {m.role === 'patient' ? 'Patient' : 'Clinic Assistant'}
                          </div>
                          <p className="whitespace-pre-wrap">{m.content}</p>
                        </div>
                        {m.at && (
                          <span className="text-[10px] text-[#64748B] mt-0.5 px-1 font-mono">
                            {formatDateTime(m.at)}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Staff Notes input */}
              <div className="space-y-2 pt-2 border-t border-[#E2E8F0]">
                <label className="text-xs font-semibold text-[#0F172A]">
                  Staff Follow-up Notes
                </label>
                <textarea
                  value={staffNote}
                  onChange={(e) => setStaffNote(e.target.value)}
                  placeholder="Add notes about your follow-up with this patient (e.g. called patient, rescheduled to Dr. Balaji)..."
                  rows={2}
                  className="w-full text-xs rounded-xl bg-[#F8FAFC] border border-[#CBD5E1] text-[#0F172A] p-3 focus:outline-none focus:border-[#14B8A6] placeholder-[#64748B]"
                />
              </div>
            </div>

            {/* Modal Footer */}
            <div className="p-4 border-t border-[#E2E8F0] bg-[#F8FAFC] flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                {selectedRequest.patient_phone && selectedRequest.patient_phone !== '-' && (
                  <a
                    href={`tel:${selectedRequest.patient_phone}`}
                    className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl bg-[#0F766E] text-white font-semibold text-xs hover:bg-[#0D9488] transition-colors shadow-sm"
                  >
                    <Phone className="w-3.5 h-3.5" />
                    <span>Call Patient</span>
                  </a>
                )}
              </div>

              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    handleUpdateStatus(selectedRequest, 'contacted', staffNote)
                    setSelectedRequest(null)
                  }}
                  className="text-xs border-[#FDE68A] text-[#B45309] hover:bg-[#FEF3C7]"
                >
                  Mark Contacted
                </Button>
                <Button
                  type="button"
                  variant="primary"
                  size="sm"
                  onClick={() => {
                    handleUpdateStatus(selectedRequest, 'resolved', staffNote)
                    setSelectedRequest(null)
                  }}
                  className="text-xs"
                >
                  Mark Resolved
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
