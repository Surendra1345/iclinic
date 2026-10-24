import React from 'react'
import { Badge } from '../../../components/ui/Badge'

const VARIANT: Record<string, 'emerald' | 'amber' | 'rose' | 'orange' | 'slate'> = {
  sent: 'emerald',
  pending: 'slate',
  retrying: 'amber',
  flagged: 'orange',
  failed: 'rose',
}

const TEXT: Record<string, string> = {
  sent: 'Confirmation sent',
  pending: 'Confirmation pending',
  retrying: 'Retrying',
  flagged: 'Flagged',
  failed: 'Failed',
}

/** How delivery of the SMS / email confirmation went; "flagged" means staff should follow up. */
export const ConfirmationBadge: React.FC<{ status?: string | null }> = ({ status }) => {
  if (!status) return null
  return (
    <Badge variant={VARIANT[status] ?? 'slate'} className="text-[10px] py-0.5">
      {TEXT[status] ?? status}
    </Badge>
  )
}
