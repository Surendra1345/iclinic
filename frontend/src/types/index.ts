export type AppointmentStatusType = 'booked' | 'rescheduled' | 'cancelled' | 'completed'

export interface AppointmentRecord {
  id: string
  patient_name: string
  patient_phone: string
  doctor_name: string
  specialty: string
  location_name: string
  location_address: string
  start_time: string
  end_time: string
  status: AppointmentStatusType
  created_at: string
}

export interface DashboardStats {
  booked_count: number
  cancelled_count: number
  rescheduled_count: number
  total_appointments: number
  total_patients: number
  total_locations: number
  total_providers: number
  forwarded_count?: number
}

export interface Doctor {
  id: string
  full_name: string
  specialty: string
}

export interface ClinicLocation {
  id: string
  name: string
  address: string
  doctors: Doctor[]
  total_doctors: number
}

export interface TargetSlotInfo {
  slot_id?: string
  doctor_name?: string
  specialty?: string
  time?: string
  location?: string
  location_name?: string
  location_address?: string
}

export interface ChatMessage {
  id: string
  sender: 'patient' | 'assistant'
  text: string
  timestamp: string
  targetSlot?: TargetSlotInfo
  isConfirmed?: boolean
}

export interface TriggerCallRequest {
  to_phone: string
}

export interface TriggerCallResponse {
  status: 'success' | 'error'
  message: string
  call_sid?: string
  to?: string
  patient_id?: string | null
  conversation_id?: string
}

export interface ChatApiRequest {
  message: string
  patient_phone?: string
  patient_name?: string
  patient_email?: string
  session_id?: string
  generate_audio?: boolean
}

export interface ChatApiResponse {
  reply: string
  session_id: string
  is_completed: boolean
  target_slot?: TargetSlotInfo
  booking_confirmed?: boolean
  audio_url?: string | null
}

export interface VoiceAssistantSessionResponse {
  session_id: string
  preferred_language: 'en-IN' | 'ta-IN' | 'te-IN'
  language_confirmed: boolean
  greeting: string
}

export interface VoiceAssistantTurnResponse extends ChatApiResponse {
  transcript: string
  language: 'en-IN' | 'ta-IN' | 'te-IN'
  language_confidence: number
  audio_url?: string | null
}

export interface ForwardedActiveAppointment {
  appointment_id: string
  doctor_name: string
  specialty: string
  location_name: string
  location_address?: string
  start_time: string
  status: string
}

export interface ForwardedRequestRecord {
  id: string
  call_sid: string
  channel: 'chat' | 'voice' | 'outbound_call' | string
  patient_id: string | null
  patient_name: string
  patient_phone: string
  patient_email?: string | null
  patient_dob?: string | null
  identity_verified?: boolean
  callback_contact_unavailable?: boolean
  awaiting_handoff_contact?: boolean
  reason: string
  raw_reason?: string
  status: 'pending' | 'contacted' | 'resolved'
  notes?: string | null
  resolved_at?: string | null
  forwarded_at: string | null
  active_appointment?: ForwardedActiveAppointment | null
  messages: Array<{
    role: 'patient' | 'agent'
    content: string
    at?: string
  }>
  total_messages: number
}

export interface ForwardedRequestsResponse {
  forwarded_requests: ForwardedRequestRecord[]
  total: number
  pending_count: number
}
