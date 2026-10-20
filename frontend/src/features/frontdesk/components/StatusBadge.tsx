import React from 'react'
import { Badge } from '../../../components/ui/Badge'
import type { AppointmentStatusType } from '../../../types'

interface StatusBadgeProps {
  status: AppointmentStatusType | string
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status }) => {
  const norm = (status || '').toLowerCase()

  if (norm === 'booked') {
    return <Badge variant="emerald">Booked</Badge>
  }
  if (norm === 'rescheduled') {
    return <Badge variant="amber">Rescheduled</Badge>
  }
  if (norm === 'cancelled') {
    return <Badge variant="rose">Cancelled</Badge>
  }
  if (norm === 'completed') {
    return <Badge variant="sky">Completed</Badge>
  }

  return <Badge variant="slate">{status}</Badge>
}
