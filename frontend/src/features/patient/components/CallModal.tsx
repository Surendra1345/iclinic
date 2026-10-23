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
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/50 backdrop-blur-sm animate-fadeIn">
      <div className="relative w-full max-w-lg bg-white border border-[#E2E8F0] rounded-2xl shadow-[var(--shadow-card)] p-6 sm:p-7 space-y-5 overflow-hidden">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-[#CCFBF1] text-[#0D9488] flex items-center justify-center border border-[#99F6E4] shadow-sm">
              <PhoneCall className="w-5 h-5 animate-pulse" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-[#0F172A] tracking-tight flex items-center gap-2">
                Request an AI Voice Call
                <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-[#CCFBF1] text-[#0D9488] border border-[#99F6E4]">
                  Instant
                </span>
              </h3>
              <p className="text-xs text-[#475569]">
                Our clinical voice agent will ring your phone directly
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleResetAndClose}
            className="text-[#64748B] hover:text-[#0F172A] p-1 rounded-lg hover:bg-[#F1F5F9] transition-colors cursor-pointer"
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
            leftIcon={<Phone className="w-4 h-4 text-[#64748B]" />}
            helperText="Include country code (+91 for India). Twilio dials this immediately."
            autoFocus
          />

          <Input
            label="Your Name (Optional)"
            placeholder="e.g. Alex"
            value={name}
            onChange={(e) => setName(e.target.value)}
            leftIcon={<User className="w-4 h-4 text-[#64748B]" />}
          />

          <div className="flex items-center gap-2 text-[11px] text-[#64748B]">
            <ShieldCheck className="w-3.5 h-3.5 text-[#14B8A6] shrink-0" />
            <span>Secure HIPAA-compliant outbound clinical gateway</span>
          </div>

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#E2E8F0]">
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
          <div className="p-4 rounded-xl bg-[#D1FAE5] border border-[#A7F3D0] text-[#059669] space-y-2 text-xs">
            <div className="flex items-center gap-2 font-semibold text-[#059669] text-sm">
              <CheckCircle2 className="w-4.5 h-4.5 text-[#059669]" />
              <span>Call Dispatched Successfully!</span>
            </div>
            <p className="text-[#059669]/90 leading-relaxed">
              Our clinical voice agent is dialing <strong className="font-mono font-bold text-[#059669]">{callResult.to}</strong>. 
              Please answer your phone to schedule your appointment.
            </p>
            {callResult.call_sid && (
              <p className="font-mono text-[11px] text-[#059669]/80 pt-1">
                Call SID: {callResult.call_sid}
              </p>
            )}
          </div>
        )}

        {/* Error message */}
        {errorMessage && (
          <div className="p-4 rounded-xl bg-[#FFE4E6] border border-[#FECDD3] text-[#E11D48] flex items-start gap-2.5 text-xs">
            <AlertCircle className="w-4 h-4 text-[#E11D48] shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-[#E11D48]">Call Dispatch Failed</p>
              <p className="text-[#E11D48]/90 mt-0.5">{errorMessage}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
