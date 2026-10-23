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
          <label htmlFor={selectId} className="block text-xs font-semibold text-[#475569]">
            {label}
          </label>
        )}
        <select
          id={selectId}
          ref={ref}
          className={cn(
            'w-full bg-white text-[#0F172A] text-sm rounded-xl border border-[#E2E8F0] hover:border-[#CBD5E1] px-3.5 py-2.5 transition-all duration-200 outline-none focus:border-[#14B8A6] focus:ring-2 focus:ring-[#14B8A6]/20 cursor-pointer shadow-xs',
            error && 'border-[#E11D48] focus:border-[#E11D48]',
            className
          )}
          {...props}
        >
          {options.map((opt, idx) => {
            const val = opt.id ?? opt.value ?? ''
            const lab = opt.label ?? opt.name ?? val
            return (
              <option key={idx} value={val} className="bg-white text-[#0F172A] py-1">
                {lab}
              </option>
            )
          })}
        </select>
        {error && <p className="text-xs text-[#E11D48] font-medium pl-1">{error}</p>}
      </div>
    )
  }
)

Select.displayName = 'Select'
