import React from 'react'
import { cn } from '../../lib/utils'

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'emerald' | 'amber' | 'rose' | 'teal' | 'slate' | 'sky' | 'orange'
  dot?: boolean
}

export const Badge: React.FC<BadgeProps> = ({
  children,
  className,
  variant = 'teal',
  dot = true,
  ...props
}) => {
  const variants = {
    emerald: 'bg-[#D1FAE5] text-[#059669] border-[#A7F3D0]',
    amber: 'bg-[#FEF3C7] text-[#B45309] border-[#FDE68A]',
    rose: 'bg-[#FFE4E6] text-[#E11D48] border-[#FECDD3]',
    orange: 'bg-[#FFEDD5] text-[#EA580C] border-[#FED7AA]',
    teal: 'bg-[#CCFBF1] text-[#0D9488] border-[#99F6E4]',
    slate: 'bg-[#F1F5F9] text-[#475569] border-[#E2E8F0]',
    sky: 'bg-[#E0F2FE] text-[#0284C7] border-[#BAE6FD]',
  }

  const dotColors = {
    emerald: 'bg-[#059669]',
    amber: 'bg-[#B45309]',
    rose: 'bg-[#E11D48]',
    orange: 'bg-[#EA580C]',
    teal: 'bg-[#0D9488]',
    slate: 'bg-[#64748B]',
    sky: 'bg-[#0284C7]',
  }

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border tracking-wide uppercase shadow-xs',
        variants[variant],
        className
      )}
      {...props}
    >
      {dot && <span className={cn('w-1.5 h-1.5 rounded-full', dotColors[variant])} />}
      {children}
    </span>
  )
}

