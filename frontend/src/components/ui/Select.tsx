import React, { forwardRef } from 'react'
import { cn } from '../../lib/utils'

export interface SelectOption {
  value: string
  label: string
}

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string
  options: readonly { id?: string; value?: string; name?: string; label?: string }[]
  error?: string
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, label, options, error, id, ...props }, ref) => {
    const selectId = id || (label ? label.toLowerCase().replace(/\s+/g, '-') : undefined)

    return (
      <div className="w-full space-y-1.5 text-left">
        {label && (
          <label htmlFor={selectId} className="block text-xs font-medium text-slate-300">
            {label}
          </label>
        )}
        <select
          id={selectId}
          ref={ref}
          className={cn(
            'w-full bg-slate-900/90 text-slate-100 text-sm rounded-xl border border-slate-700/80 px-3.5 py-2.5 transition-all duration-200 outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-400/20 cursor-pointer shadow-inner',
            error && 'border-rose-500/80 focus:border-rose-500',
            className
          )}
          {...props}
        >
          {options.map((opt, idx) => {
            const val = opt.id ?? opt.value ?? ''
            const lab = opt.label ?? opt.name ?? val
            return (
              <option key={idx} value={val} className="bg-slate-900 text-slate-100 py-1">
                {lab}
              </option>
            )
          })}
        </select>
        {error && <p className="text-xs text-rose-400 font-medium pl-1">{error}</p>}
      </div>
    )
  }
)

Select.displayName = 'Select'
