import React from 'react'
import { cn } from '../../lib/utils'

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'emerald' | 'amber' | 'rose' | 'teal' | 'slate' | 'sky'
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
    emerald: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20 shadow-emerald-500/10',
    amber: 'bg-amber-500/10 text-amber-400 border-amber-500/20 shadow-amber-500/10',
    rose: 'bg-rose-500/10 text-rose-400 border-rose-500/20 shadow-rose-500/10',
    teal: 'bg-teal-500/10 text-teal-300 border-teal-500/20 shadow-teal-500/10',
    slate: 'bg-slate-800/80 text-slate-300 border-slate-700 shadow-slate-900/10',
    sky: 'bg-sky-500/10 text-sky-400 border-sky-500/20 shadow-sky-500/10',
  }

  const dotColors = {
    emerald: 'bg-emerald-400',
    amber: 'bg-amber-400',
    rose: 'bg-rose-400',
    teal: 'bg-teal-400',
    slate: 'bg-slate-400',
    sky: 'bg-sky-400',
  }

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border tracking-wide uppercase shadow-sm',
        variants[variant],
        className
      )}
      {...props}
    >
      {dot && <span className={cn('w-1.5 h-1.5 rounded-full animate-pulse', dotColors[variant])} />}
      {children}
    </span>
  )
}
