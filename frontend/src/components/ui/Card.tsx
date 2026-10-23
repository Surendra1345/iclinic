import React from 'react'
import { cn } from '../../lib/utils'

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  glow?: 'none' | 'teal' | 'emerald' | 'rose' | 'amber'
}

export const Card: React.FC<CardProps> = ({
  children,
  className,
  glow = 'none',
  ...props
}) => {
  const glowStyles = {
    none: 'border-[#E2E8F0] hover:border-[#CBD5E1]',
    teal: 'border-[#CCFBF1] hover:border-[#14B8A6]',
    emerald: 'border-[#A7F3D0] hover:border-[#059669]',
    rose: 'border-[#FECDD3] hover:border-[#E11D48]',
    amber: 'border-[#FDE68A] hover:border-[#B45309]',
  }

  return (
    <div
      className={cn(
        'bg-white rounded-2xl p-6 transition-all duration-200 relative overflow-hidden border shadow-[var(--shadow-card)] text-[#0F172A]',
        glowStyles[glow],
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
}

