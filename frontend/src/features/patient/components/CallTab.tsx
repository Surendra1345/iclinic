import React, { useState } from 'react'
import { Phone, PhoneCall, CheckCircle2, AlertCircle, Clock, ShieldCheck, Sparkles, Building2, User } from 'lucide-react'
import { Card } from '../../../components/ui/Card'
import { Button } from '../../../components/ui/Button'
import { Input } from '../../../components/ui/Input'
import { Badge } from '../../../components/ui/Badge'
import { useTriggerCall } from '../queries/patientQueries'
import { ENV } from '../../../config/env'
import type { TriggerCallResponse } from '../../../types'

export const CallTab: React.FC = () => {
  const [phone, setPhone] = useState(ENV.DEFAULT_PHONE)
  const [patientName, setPatientName] = useState('')
  const [callResult, setCallResult] = useState<TriggerCallResponse | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const triggerCallMutation = useTriggerCall()

  const handleStartCall = async (e: React.FormEvent) => {
    e.preventDefault()
    setErrorMessage(null)
    setCallResult(null)

    // Basic phone validation
    const cleaned = phone.trim()
    if (!cleaned || cleaned.length < 10) {
      setErrorMessage('Please enter a valid phone number with country code (e.g., +919876543210)')
      return
    }

    try {
      const response = await triggerCallMutation.mutateAsync({ to_phone: cleaned })
      setCallResult(response)
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to initiate outbound call. Please check server.')
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Intro Header */}
      <div className="text-center space-y-2">
        <Badge variant="teal" className="mb-1">
          <Sparkles className="w-3 h-3 text-[#0D9488] mr-1 inline" /> Instant AI Voice Callback
        </Badge>
        <h2 className="text-2xl sm:text-3xl font-semibold text-[#0F172A] tracking-tight">
          Request an Outbound Appointment Call
        </h2>
        <p className="text-sm sm:text-base text-[#475569] max-w-xl mx-auto">
          Enter your phone number below and our AI scheduling assistant will dial you within seconds to book, reschedule, or cancel your clinic appointment.
        </p>
      </div>

      {/* Main Action Card */}
      <Card glow="teal" className="border-[#E2E8F0]">
        <form onSubmit={handleStartCall} className="space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Input
              label="Your Full Name"
              placeholder="e.g. Surendra"
              value={patientName}
              onChange={(e) => setPatientName(e.target.value)}
              leftIcon={<User className="w-4 h-4 text-[#64748B]" />}
            />
            <Input
              label="Phone Number (E.164 with Country Code)"
              placeholder="+916303023283"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              leftIcon={<Phone className="w-4 h-4 text-[#64748B]" />}
              helperText="Twilio outbound call will ring this number immediately"
            />
          </div>

          <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-2 border-t border-[#E2E8F0]">
            <div className="flex items-center gap-2 text-xs text-[#64748B]">
              <ShieldCheck className="w-4 h-4 text-[#14B8A6] shrink-0" />
              <span>Verified HIPAA-compliant clinical telephone gateway</span>
            </div>

            <Button
              type="submit"
              size="lg"
              variant="primary"
              className="w-full sm:w-auto min-w-[200px]"
              isLoading={triggerCallMutation.isPending}
              leftIcon={<PhoneCall className="w-5 h-5 animate-pulse" />}
            >
              {triggerCallMutation.isPending ? 'Connecting Gateway...' : 'Call Me Now'}
            </Button>
          </div>
        </form>

        {/* Success Status Message */}
        {callResult && (
          <div className="mt-6 p-4 rounded-xl bg-[#D1FAE5] border border-[#A7F3D0] text-[#059669] space-y-3 animate-fadeIn">
            <div className="flex items-center gap-2.5 font-semibold text-[#059669]">
              <CheckCircle2 className="w-5 h-5 text-[#059669] shrink-0" />
              <span>Call Dispatched Successfully!</span>
            </div>
            <p className="text-xs sm:text-sm text-[#059669]/90 leading-relaxed">
              Our clinical voice agent is calling <strong className="font-mono font-bold text-[#059669]">{callResult.to}</strong>. 
              Please answer your phone to speak with the scheduling assistant.
            </p>
            {callResult.call_sid && (
              <div className="flex flex-wrap items-center gap-3 pt-2 text-xs border-t border-[#A7F3D0] font-mono text-[#059669]">
                <span className="bg-[#A7F3D0]/40 px-2 py-0.5 rounded border border-[#A7F3D0]">
                  Call SID: {callResult.call_sid}
                </span>
                {callResult.conversation_id && (
                  <span className="text-[#059669]/80">
                    Convo ID: {callResult.conversation_id.slice(0, 8)}...
                  </span>
                )}
              </div>
            )}
          </div>
        )}

        {/* Error Message */}
        {errorMessage && (
          <div className="mt-6 p-4 rounded-xl bg-[#FFE4E6] border border-[#FECDD3] text-[#E11D48] flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-[#E11D48] shrink-0 mt-0.5" />
            <div className="text-sm space-y-1">
              <p className="font-semibold text-[#E11D48]">Outbound Call Notice</p>
              <p className="text-[#E11D48]/90">{errorMessage}</p>
            </div>
          </div>
        )}
      </Card>

      {/* Feature Walkthrough Pills */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
        <div className="p-4 rounded-xl bg-white border border-[#E2E8F0] shadow-[var(--shadow-card)] space-y-1.5">
          <div className="w-8 h-8 rounded-lg bg-[#CCFBF1] flex items-center justify-center text-[#0D9488] mb-2">
            <Clock className="w-4 h-4" />
          </div>
          <h4 className="text-sm font-semibold text-[#0F172A]">Zero Wait Time</h4>
          <p className="text-xs text-[#475569] leading-relaxed">
            The AI dials immediately. No waiting on hold, listening to music, or navigating IVR menus.
          </p>
        </div>

        <div className="p-4 rounded-xl bg-white border border-[#E2E8F0] shadow-[var(--shadow-card)] space-y-1.5">
          <div className="w-8 h-8 rounded-lg bg-[#E0F2FE] flex items-center justify-center text-[#0284C7] mb-2">
            <Building2 className="w-4 h-4" />
          </div>
          <h4 className="text-sm font-semibold text-[#0F172A]">4 Clinic Locations</h4>
          <p className="text-xs text-[#475569] leading-relaxed">
            Select your preferred branch across Anna Nagar, T. Nagar, Velachery, or Tambaram.
          </p>
        </div>

        <div className="p-4 rounded-xl bg-white border border-[#E2E8F0] shadow-[var(--shadow-card)] space-y-1.5">
          <div className="w-8 h-8 rounded-lg bg-[#D1FAE5] flex items-center justify-center text-[#059669] mb-2">
            <CheckCircle2 className="w-4 h-4" />
          </div>
          <h4 className="text-sm font-semibold text-[#0F172A]">Instant SMS & DB Sync</h4>
          <p className="text-xs text-[#475569] leading-relaxed">
            Confirmed appointments are saved to the clinical Postgres database and visible to the frontdesk in real-time.
          </p>
        </div>
      </div>
    </div>
  )
}
