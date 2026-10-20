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
    none: 'border-slate-800/80 hover:border-slate-700/80',
    teal: 'border-teal-500/30 hover:border-teal-400/50 shadow-lg shadow-teal-500/5',
    emerald: 'border-emerald-500/30 hover:border-emerald-400/50 shadow-lg shadow-emerald-500/5',
    rose: 'border-rose-500/30 hover:border-rose-400/50 shadow-lg shadow-rose-500/5',
    amber: 'border-amber-500/30 hover:border-amber-400/50 shadow-lg shadow-amber-500/5',
  }

  return (
    <div
      className={cn(
        'glass-panel rounded-2xl p-6 transition-all duration-300 relative overflow-hidden',
        glowStyles[glow],
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
}
