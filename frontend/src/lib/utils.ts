import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

const CLINIC_TIME_ZONE = 'Asia/Kolkata'

/** Joins class names and resolves conflicting Tailwind classes. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

function toDate(value?: string | number | Date | null): Date | null {
  if (value === undefined || value === null || value === '') return null
  const date = value instanceof Date ? value : new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

/** Time of day in clinic time (IST), for example "03:42 pm" or "03:42:09 pm". */
export function formatClockIST(value?: string | number | Date | null, withSeconds = false): string {
  const date = toDate(value)
  if (!date) return '-'
  return date.toLocaleTimeString('en-IN', {
    timeZone: CLINIC_TIME_ZONE,
    hour: '2-digit',
    minute: '2-digit',
    ...(withSeconds ? { second: '2-digit' } : {}),
  })
}

/** Date and time in clinic time (IST), for example "14 Mar, 03:42 pm". */
export function formatDateTime(value?: string | number | Date | null): string {
  const date = toDate(value)
  if (!date) return '-'
  return date.toLocaleString('en-IN', {
    timeZone: CLINIC_TIME_ZONE,
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** "+919876543210" becomes "+91 98765 43210"; anything else is shown as given. */
export function formatPhone(value?: string | null): string {
  const raw = (value ?? '').trim()
  if (!raw) return '-'
  const digits = raw.replace(/\D/g, '')
  if (digits.length === 12 && digits.startsWith('91')) {
    return `+91 ${digits.slice(2, 7)} ${digits.slice(7)}`
  }
  if (digits.length === 10) {
    return `${digits.slice(0, 5)} ${digits.slice(5)}`
  }
  return raw
}
