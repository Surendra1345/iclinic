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
          <Sparkles className="w-3 h-3 text-teal-400 mr-1 inline" /> Instant AI Voice Callback
        </Badge>
        <h2 className="text-2xl sm:text-3xl font-semibold text-white tracking-tight">
          Request an Outbound Appointment Call
        </h2>
        <p className="text-sm sm:text-base text-slate-400 max-w-xl mx-auto">
          Enter your phone number below and our AI scheduling assistant will dial you within seconds to book, reschedule, or cancel your clinic appointment.
        </p>
      </div>

      {/* Main Action Card */}
      <Card glow="teal" className="border-teal-500/30">
        <form onSubmit={handleStartCall} className="space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Input
              label="Your Full Name"
              placeholder="e.g. Surendra"
              value={patientName}
              onChange={(e) => setPatientName(e.target.value)}
              leftIcon={<User className="w-4 h-4" />}
            />
            <Input
              label="Phone Number (E.164 with Country Code)"
              placeholder="+916303023283"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              leftIcon={<Phone className="w-4 h-4" />}
              helperText="Twilio outbound call will ring this number immediately"
            />
          </div>

          <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-2 border-t border-slate-800">
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <ShieldCheck className="w-4 h-4 text-teal-400 shrink-0" />
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
          <div className="mt-6 p-4 rounded-xl bg-teal-950/60 border border-teal-500/40 text-teal-200 space-y-3 animate-fadeIn">
            <div className="flex items-center gap-2.5 font-semibold text-teal-300">
              <CheckCircle2 className="w-5 h-5 text-teal-400 shrink-0" />
              <span>Call Dispatched Successfully!</span>
            </div>
            <p className="text-xs sm:text-sm text-teal-100/90 leading-relaxed">
              Our clinical voice agent is calling <strong className="text-white font-mono">{callResult.to}</strong>. 
              Please answer your phone to speak with the scheduling assistant.
            </p>
            {callResult.call_sid && (
              <div className="flex flex-wrap items-center gap-3 pt-2 text-xs border-t border-teal-800/60 font-mono text-teal-300">
                <span className="bg-teal-900/60 px-2 py-0.5 rounded border border-teal-700/50">
                  Call SID: {callResult.call_sid}
                </span>
                {callResult.conversation_id && (
                  <span className="text-teal-400/80">
                    Convo ID: {callResult.conversation_id.slice(0, 8)}...
                  </span>
                )}
              </div>
            )}
          </div>
        )}

        {/* Error Message */}
        {errorMessage && (
          <div className="mt-6 p-4 rounded-xl bg-rose-950/50 border border-rose-500/40 text-rose-200 flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
            <div className="text-sm space-y-1">
              <p className="font-semibold text-rose-300">Outbound Call Notice</p>
              <p className="text-rose-200/90">{errorMessage}</p>
            </div>
          </div>
        )}
      </Card>

      {/* Feature Walkthrough Pills */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-1.5">
          <div className="w-8 h-8 rounded-lg bg-teal-500/10 flex items-center justify-center text-teal-400 mb-2">
            <Clock className="w-4 h-4" />
          </div>
          <h4 className="text-sm font-semibold text-slate-200">Zero Wait Time</h4>
          <p className="text-xs text-slate-400 leading-relaxed">
            The AI dials immediately. No waiting on hold, listening to music, or navigating IVR menus.
          </p>
        </div>

        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-1.5">
          <div className="w-8 h-8 rounded-lg bg-cyan-500/10 flex items-center justify-center text-cyan-400 mb-2">
            <Building2 className="w-4 h-4" />
          </div>
          <h4 className="text-sm font-semibold text-slate-200">4 Clinic Locations</h4>
          <p className="text-xs text-slate-400 leading-relaxed">
            Select your preferred branch across Anna Nagar, T. Nagar, Velachery, or Tambaram.
          </p>
        </div>

        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-1.5">
          <div className="w-8 h-8 rounded-lg bg-emerald-500/10 flex items-center justify-center text-emerald-400 mb-2">
            <CheckCircle2 className="w-4 h-4" />
          </div>
          <h4 className="text-sm font-semibold text-slate-200">Instant SMS & DB Sync</h4>
          <p className="text-xs text-slate-400 leading-relaxed">
            Confirmed appointments are saved to the clinical Postgres database and visible to the frontdesk in real-time.
          </p>
        </div>
      </div>
    </div>
  )
}
