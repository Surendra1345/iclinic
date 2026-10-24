import React, { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ArrowDownUp, Bot, Inbox, MessageSquare, RefreshCw, RotateCcw, Search, User, X } from 'lucide-react'
import { Badge } from '../../../components/ui/Badge'
import { Button } from '../../../components/ui/Button'
import { Card } from '../../../components/ui/Card'
import { Input } from '../../../components/ui/Input'
import { Select } from '../../../components/ui/Select'
import {
  CHANNEL_FILTERS,
  CONFIRMATION_STATUS_FILTERS,
  CONVERSATION_SORT_OPTIONS,
  CONVERSATION_STATE_FILTERS,
} from '../../../config/constants'
import { formatClockIST, formatDateTime, formatPhone } from '../../../lib/utils'
import { useConversationDetail, useConversations } from '../queries/frontdeskQueries'
import { RefreshButton } from './RefreshButton'
import { ConfirmationBadge } from './ConfirmationBadge'

const label = (value?: string | null) => (value ? value.replace(/_/g, ' ') : '-')

const STATE_VARIANT: Record<string, 'emerald' | 'amber' | 'rose' | 'orange' | 'sky' | 'slate'> = {
  booked: 'emerald',
  rescheduled: 'amber',
  cancelled: 'rose',
  handed_to_front_desk: 'orange',
  failed: 'rose',
  abandoned: 'slate',
}

const StateBadge: React.FC<{ state?: string | null }> = ({ state }) => (
  <Badge variant={STATE_VARIANT[state ?? ''] ?? 'sky'} className="capitalize">
    {label(state)}
  </Badge>
)

const ConversationDetailPanel: React.FC<{ id: string; onClose: () => void }> = ({ id, onClose }) => {
  const { data, isLoading } = useConversationDetail(id)

  return (
    <>
      {/* Small screens: the conversation slides over the page; tap outside to close */}
      <div className="fixed inset-0 z-40 bg-black/30 lg:hidden" onClick={onClose} aria-hidden="true" />
      <div className="fixed inset-y-0 right-0 z-50 w-full max-w-lg overflow-y-auto bg-[#F6F9FB] p-3 shadow-2xl lg:sticky lg:inset-auto lg:top-20 lg:z-auto lg:max-w-none lg:overflow-visible lg:bg-transparent lg:p-0 lg:shadow-none">
    <Card glow="none" className="p-4 sm:p-5 space-y-5 border-[#99F6E4] lg:max-h-[calc(100vh-7rem)] lg:overflow-y-auto">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-[#0F172A]">
            {data?.patient_name || 'Anonymous / Guest'}
          </h3>
          {data && (
            <p className="text-xs text-[#64748B] mt-0.5 capitalize">
              {label(data.channel)} · started {formatDateTime(data.started_at ?? '')}
              {data.confirmation_status ? ` · confirmation ${label(data.confirmation_status)}` : ''}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-[#64748B] hover:text-[#0F172A] p-1 cursor-pointer"
          title="Close"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {isLoading || !data ? (
        <div className="py-8 text-center text-[#64748B] text-sm">
          <RefreshCw className="w-5 h-5 animate-spin mx-auto text-[#14B8A6] mb-2" />
          Loading conversation...
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-5">
          {/* Transcript */}
          <div className="space-y-2">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-[#475569]">Transcript</h4>
            <div className="max-h-[320px] overflow-y-auto space-y-2 pr-1">
              {data.messages.length === 0 && (
                <p className="text-xs text-[#64748B]">No messages recorded.</p>
              )}
              {data.messages.map((m, i) => {
                const fromPatient = m.role === 'patient'
                return (
                  <div key={i} className={`flex items-start gap-2 ${fromPatient ? 'justify-end' : ''}`}>
                    {!fromPatient && <Bot className="w-4 h-4 text-[#0D9488] mt-1 shrink-0" />}
                    <div
                      className={`max-w-[85%] rounded-xl px-3 py-2 text-xs leading-relaxed ${
                        fromPatient
                          ? 'bg-[#0F766E] text-white'
                          : 'bg-[#F8FAFC] border border-[#E2E8F0] text-[#0F172A]'
                      }`}
                    >
                      <p className="whitespace-pre-wrap">{m.content}</p>
                      {m.at && <p className="opacity-60 text-[10px] mt-1">{formatDateTime(m.at)}</p>}
                    </div>
                    {fromPatient && <User className="w-4 h-4 text-[#0F766E] mt-1 shrink-0" />}
                  </div>
                )
              })}
            </div>
          </div>

          <div className="space-y-5">
            {/* State timeline */}
            <div className="space-y-2">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-[#475569]">State timeline</h4>
              {data.state_history.length === 0 ? (
                <p className="text-xs text-[#64748B]">No state changes recorded.</p>
              ) : (
                <ol className="border-l-2 border-[#99F6E4] pl-4 space-y-2">
                  {data.state_history.map((entry, i) => (
                    <li key={i} className="text-xs">
                      <span className="font-semibold text-[#0F172A] capitalize">{label(entry.state)}</span>
                      <span className="text-[#64748B]"> · {formatDateTime(entry.at)}</span>
                    </li>
                  ))}
                </ol>
              )}
            </div>

            {/* Step log */}
            <div className="space-y-2">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-[#475569]">Step log</h4>
              <div className="max-h-[220px] overflow-auto border border-[#E2E8F0] rounded-xl">
                <table className="w-full text-[11px] text-left">
                  <thead className="bg-[#F1F5F9] text-[#475569] sticky top-0">
                    <tr>
                      <th className="py-2 px-2">Time</th>
                      <th className="py-2 px-2">Patient said</th>
                      <th className="py-2 px-2">Agent replied</th>
                      <th className="py-2 px-2">Result</th>
                      <th className="py-2 px-2">Intent</th>
                      <th className="py-2 px-2">State</th>
                      <th className="py-2 px-2">Waiting for</th>
                      <th className="py-2 px-2 text-right">ms</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#E2E8F0]">
                    {data.step_logs.length === 0 && (
                      <tr>
                        <td colSpan={9} className="py-3 px-2 text-[#64748B]">
                          No steps recorded.
                        </td>
                      </tr>
                    )}
                    {data.step_logs.map((step, i) => (
                      <tr key={i} className={step.error_stage ? 'bg-[#FFF1F2]' : ''}>
                        <td className="py-1.5 px-2 whitespace-nowrap">
                          {formatClockIST(step.at, true)}
                        </td>
                        <td className="py-1.5 px-2 max-w-[140px] truncate" title={step.input}>{step.input || '-'}</td>
                        <td className="py-1.5 px-2 max-w-[180px] truncate" title={step.output}>{step.output || '-'}</td>
                        <td className="py-1.5 px-2">
                          <span
                            className={`px-1.5 py-0.5 rounded-md font-semibold capitalize ${
                              step.result === 'error'
                                ? 'bg-[#FFE4E6] text-[#E11D48]'
                                : step.result === 'warning'
                                ? 'bg-[#FEF3C7] text-[#B45309]'
                                : 'bg-[#D1FAE5] text-[#047857]'
                            }`}
                          >
                            {step.result ?? 'success'}
                          </span>
                        </td>
                        <td className="py-1.5 px-2 capitalize">{label(step.intent)}</td>
                        <td className="py-1.5 px-2 capitalize">{label(step.state)}</td>
                        <td className="py-1.5 px-2">
                          {step.error_stage
                            ? `error: ${label(step.error_stage)}`
                            : step.waiting_for?.length
                            ? step.waiting_for.map(label).join(', ')
                            : '-'}
                        </td>
                        <td className="py-1.5 px-2 text-right font-mono">{step.elapsed_ms ?? '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}
    </Card>
      </div>
    </>
  )
}

export const ConversationsTable: React.FC = () => {
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [channel, setChannel] = useState('all')
  const [state, setState] = useState('all')
  const [confirmation, setConfirmation] = useState('all')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [sortBy, setSortBy] = useState('updated_at')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search.trim()), 250)
    return () => clearTimeout(timer)
  }, [search])

  const queryClient = useQueryClient()
  const { data, isLoading, refetch, dataUpdatedAt } = useConversations({
    search: debouncedSearch || undefined,
    channel: channel !== 'all' ? channel : undefined,
    state: state !== 'all' ? state : undefined,
    confirmation_status: confirmation !== 'all' ? confirmation : undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    sort: sortBy,
    order: sortOrder,
  })
  const conversations = data?.conversations ?? []

  const isFiltered =
    search !== '' || channel !== 'all' || state !== 'all' || confirmation !== 'all' || dateFrom !== '' || dateTo !== ''

  const resetFilters = () => {
    setSearch('')
    setDebouncedSearch('')
    setChannel('all')
    setState('all')
    setConfirmation('all')
    setDateFrom('')
    setDateTo('')
  }

  return (
    <div className="space-y-4">
      <Card glow="none" className="p-4 sm:p-5 space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 items-end">
          <Input
            placeholder="Search patient, phone, or call ID..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            leftIcon={<Search className="w-4 h-4 text-[#64748B]" />}
            className="h-10 text-xs"
          />
          <Select
            options={CHANNEL_FILTERS}
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
            className="h-10 text-xs"
          />
          <Select
            options={CONVERSATION_STATE_FILTERS}
            value={state}
            onChange={(e) => setState(e.target.value)}
            className="h-10 text-xs"
          />
          <RefreshButton
            className="w-full"
            updatedAt={dataUpdatedAt}
            onRefresh={() =>
              Promise.all([
                refetch(),
                selectedId
                  ? queryClient.refetchQueries({ queryKey: ['dashboard', 'conversation', selectedId] })
                  : Promise.resolve(),
              ])
            }
          />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 items-end">
          <Select
            options={CONFIRMATION_STATUS_FILTERS}
            value={confirmation}
            onChange={(e) => setConfirmation(e.target.value)}
            className="h-10 text-xs"
          />
          <Input
            type="date"
            label="Started from"
            value={dateFrom}
            max={dateTo || undefined}
            onChange={(e) => setDateFrom(e.target.value)}
            className="h-10 text-xs"
          />
          <Input
            type="date"
            label="Started to"
            value={dateTo}
            min={dateFrom || undefined}
            onChange={(e) => setDateTo(e.target.value)}
            className="h-10 text-xs"
          />
          <Select
            options={CONVERSATION_SORT_OPTIONS}
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
            {sortOrder === 'asc' ? 'Oldest first' : 'Newest first'}
          </Button>
        </div>
        {isFiltered && (
          <div className="flex justify-end pt-2 border-t border-[#E2E8F0]">
            <button
              type="button"
              onClick={resetFilters}
              className="text-[#E11D48] hover:text-[#BE123C] font-semibold text-xs flex items-center gap-1 cursor-pointer"
            >
              <RotateCcw className="w-3 h-3" />
              Reset Filters
            </button>
          </div>
        )}
      </Card>

      <div className={selectedId ? 'grid gap-4 lg:grid-cols-2 items-start' : ''}>
      <Card glow="none" className="p-0 overflow-hidden border-[#E2E8F0] min-w-0">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border-collapse">
            <thead>
              <tr className="border-b border-[#E2E8F0] bg-[#F1F5F9] text-[11px] font-semibold uppercase tracking-wider text-[#475569]">
                <th className="py-3.5 px-4">Patient</th>
                <th className="py-3.5 px-4">Channel</th>
                <th className="py-3.5 px-4">State</th>
                <th className={`py-3.5 px-4 ${selectedId ? 'hidden xl:table-cell' : ''}`}>Outcome</th>
                <th className={`py-3.5 px-4 ${selectedId ? 'hidden xl:table-cell' : ''}`}>Messages</th>
                <th className={`py-3.5 px-4 ${selectedId ? 'hidden xl:table-cell' : ''}`}>Last activity</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E2E8F0]">
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-[#64748B]">
                    <RefreshCw className="w-6 h-6 animate-spin mx-auto text-[#14B8A6] mb-2" />
                    Loading conversations...
                  </td>
                </tr>
              ) : conversations.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-14 text-center text-[#64748B]">
                    <Inbox className="w-8 h-8 mx-auto text-[#94A3B8] mb-1" />
                    <p className="text-sm font-semibold text-[#0F172A]">No conversations found</p>
                    <p className="text-xs">
                      {isFiltered ? 'Try adjusting or clearing your filters.' : 'No conversations recorded yet.'}
                    </p>
                  </td>
                </tr>
              ) : (
                conversations.map((c) => (
                  <tr
                    key={c.id}
                    onClick={() => setSelectedId(c.id)}
                    className={`cursor-pointer hover:bg-[#F8FAFC] transition-colors ${
                      selectedId === c.id ? 'bg-[#F0FDFA]' : ''
                    }`}
                  >
                    <td className="py-3.5 px-4">
                      <p className="font-semibold text-[#0F172A] text-xs sm:text-sm">{c.patient_name}</p>
                      <p className="text-[11px] text-[#475569] font-mono">
                        {c.patient_phone !== '-' ? formatPhone(c.patient_phone) : '-'}
                      </p>
                    </td>
                    <td className="py-3.5 px-4 text-xs capitalize">{label(c.channel)}</td>
                    <td className="py-3.5 px-4">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <StateBadge state={c.current_state} />
                        <ConfirmationBadge status={c.confirmation_status} />
                      </div>
                    </td>
                    <td className={`py-3.5 px-4 text-xs capitalize ${selectedId ? 'hidden xl:table-cell' : ''}`}>{label(c.outcome)}</td>
                    <td className={`py-3.5 px-4 text-xs ${selectedId ? 'hidden xl:table-cell' : ''}`}>
                      <span className="inline-flex items-center gap-1">
                        <MessageSquare className="w-3.5 h-3.5 text-[#64748B]" />
                        {c.total_messages}
                      </span>
                    </td>
                    <td className={`py-3.5 px-4 text-xs text-[#64748B] ${selectedId ? 'hidden xl:table-cell' : ''}`}>{formatDateTime(c.updated_at ?? '')}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <div className="py-3 px-4 bg-[#F1F5F9] border-t border-[#E2E8F0] text-xs text-[#475569] flex items-center justify-between">
          <span>Showing {conversations.length} conversations (click one to open its transcript and step log)</span>
          <span className="text-[11px] text-[#0D9488] font-medium">Auto-refresh active (5s interval)</span>
        </div>
      </Card>
      {selectedId && <ConversationDetailPanel id={selectedId} onClose={() => setSelectedId(null)} />}
      </div>
    </div>
  )
}
