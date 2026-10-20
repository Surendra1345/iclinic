import React, { useState } from 'react'
import {
  PhoneCall,
  X,
  Phone,
  User,
  CheckCircle2,
  AlertCircle,
  ShieldCheck,
} from 'lucide-react'
import { Button } from '../../../components/ui/Button'
import { Input } from '../../../components/ui/Input'
import { useTriggerCall } from '../queries/patientQueries'
import type { TriggerCallResponse } from '../../../types'

interface CallModalProps {
  isOpen: boolean
  onClose: () => void
}

export const CallModal: React.FC<CallModalProps> = ({ isOpen, onClose }) => {
  const [phone, setPhone] = useState('')
  const [name, setName] = useState('')
  const [callResult, setCallResult] = useState<TriggerCallResponse | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const triggerCallMutation = useTriggerCall()

  if (!isOpen) return null

  const handleStartCall = async (e: React.FormEvent) => {
    e.preventDefault()
    setErrorMessage(null)
    setCallResult(null)

    const cleaned = phone.trim()
    if (!cleaned || cleaned.length < 10) {
      setErrorMessage('Please enter a valid phone number with country code (e.g. +919876543210)')
      return
    }

    try {
      const response = await triggerCallMutation.mutateAsync({ to_phone: cleaned })
      setCallResult(response)
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to dispatch outbound call. Please verify backend.')
    }
  }

  const handleResetAndClose = () => {
    setCallResult(null)
    setErrorMessage(null)
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-md animate-fadeIn">
      <div className="relative w-full max-w-lg bg-slate-900 border border-slate-700/80 rounded-2xl shadow-2xl p-6 sm:p-7 space-y-5 overflow-hidden">
        {/* Background glow */}
        <div className="absolute top-0 right-0 w-48 h-48 bg-teal-500/10 rounded-full blur-3xl pointer-events-none" />

        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-teal-500/20 text-teal-400 flex items-center justify-center border border-teal-500/30 shadow-md">
              <PhoneCall className="w-5 h-5 animate-pulse" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-white tracking-tight flex items-center gap-2">
                Request an AI Voice Call
                <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-teal-500/20 text-teal-300 border border-teal-500/30">
                  Instant
                </span>
              </h3>
              <p className="text-xs text-slate-400">
                Our clinical voice agent will ring your phone directly
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleResetAndClose}
            className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Call Form */}
        <form onSubmit={handleStartCall} className="space-y-4">
          <Input
            label="Your Phone Number (Required)"
            placeholder="+919876543210"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            leftIcon={<Phone className="w-4 h-4 text-slate-400" />}
            helperText="Include country code (+91 for India). Twilio dials this immediately."
            autoFocus
          />

          <Input
            label="Your Name (Optional)"
            placeholder="e.g. Alex"
            value={name}
            onChange={(e) => setName(e.target.value)}
            leftIcon={<User className="w-4 h-4 text-slate-400" />}
          />

          <div className="flex items-center gap-2 text-[11px] text-slate-400">
            <ShieldCheck className="w-3.5 h-3.5 text-teal-400 shrink-0" />
            <span>Secure HIPAA-compliant outbound clinical gateway</span>
          </div>

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
            <Button
              type="button"
              variant="outline"
              size="md"
              onClick={handleResetAndClose}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              size="md"
              isLoading={triggerCallMutation.isPending}
              leftIcon={<PhoneCall className="w-4 h-4" />}
            >
              {triggerCallMutation.isPending ? 'Connecting Gateway...' : 'Call Me Now'}
            </Button>
          </div>
        </form>

        {/* Success message */}
        {callResult && (
          <div className="p-4 rounded-xl bg-teal-950/70 border border-teal-500/40 text-teal-200 space-y-2 text-xs">
            <div className="flex items-center gap-2 font-semibold text-teal-300 text-sm">
              <CheckCircle2 className="w-4.5 h-4.5 text-teal-400" />
              <span>Call Dispatched Successfully!</span>
            </div>
            <p className="text-teal-200/90 leading-relaxed">
              Our clinical voice agent is dialing <strong className="text-white font-mono">{callResult.to}</strong>. 
              Please answer your phone to schedule your appointment.
            </p>
            {callResult.call_sid && (
              <p className="font-mono text-[11px] text-teal-400/80 pt-1">
                Call SID: {callResult.call_sid}
              </p>
            )}
          </div>
        )}

        {/* Error message */}
        {errorMessage && (
          <div className="p-4 rounded-xl bg-rose-950/60 border border-rose-500/40 text-rose-200 flex items-start gap-2.5 text-xs">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-rose-300">Call Dispatch Failed</p>
              <p className="text-rose-200/90 mt-0.5">{errorMessage}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
