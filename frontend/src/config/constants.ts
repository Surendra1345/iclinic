export const CLINIC_BRANCHES = [
  { id: 'all', name: 'All Branches' },
  { id: 'anna-nagar', name: 'Anna Nagar' },
  { id: 't-nagar', name: 'T. Nagar' },
  { id: 'velachery', name: 'Velachery' },
  { id: 'tambaram', name: 'Tambaram' },
] as const

export const APPOINTMENT_STATUS_FILTERS = [
  { id: 'all', label: 'All Statuses' },
  { id: 'booked', label: 'Booked' },
  { id: 'rescheduled', label: 'Rescheduled' },
  { id: 'cancelled', label: 'Cancelled' },
] as const

export const PATIENT_PROMPT_PRESETS = [
  {
    category: 'Booking',
    text: 'I want to book an appointment for tomorrow',
  },
  {
    category: 'Cardiology',
    text: 'Do you have a cardiologist available in Anna Nagar?',
  },
  {
    category: 'Dentistry',
    text: 'I have severe tooth pain and need an appointment in Velachery',
  },
  {
    category: 'Rescheduling',
    text: 'I need to reschedule my existing appointment',
  },
  {
    category: 'Cancellation',
    text: 'Please cancel my appointment',
  },
  {
    category: 'General Inquiry',
    text: 'Which doctors are available in T. Nagar branch?',
  },
] as const

export const STATUS_THEMES: Record<string, { bg: string; text: string; border: string; glow: string; dot: string }> = {
  booked: {
    bg: 'bg-emerald-500/10',
    text: 'text-emerald-400',
    border: 'border-emerald-500/20',
    glow: 'shadow-emerald-500/20',
    dot: 'bg-emerald-400',
  },
  rescheduled: {
    bg: 'bg-amber-500/10',
    text: 'text-amber-400',
    border: 'border-amber-500/20',
    glow: 'shadow-amber-500/20',
    dot: 'bg-amber-400',
  },
  cancelled: {
    bg: 'bg-rose-500/10',
    text: 'text-rose-400',
    border: 'border-rose-500/20',
    glow: 'shadow-rose-500/20',
    dot: 'bg-rose-400',
  },
  completed: {
    bg: 'bg-sky-500/10',
    text: 'text-sky-400',
    border: 'border-sky-500/20',
    glow: 'shadow-sky-500/20',
    dot: 'bg-sky-400',
  },
}
