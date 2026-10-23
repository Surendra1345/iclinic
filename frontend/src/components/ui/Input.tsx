import React, { forwardRef } from 'react'
import { cn } from '../../lib/utils'

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  leftIcon?: React.ReactNode
  rightElement?: React.ReactNode
  helperText?: string
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, error, leftIcon, rightElement, helperText, id, ...props }, ref) => {
    const inputId = id || (label ? label.toLowerCase().replace(/\s+/g, '-') : undefined)

    return (
      <div className="w-full space-y-1.5 text-left">
        {label && (
          <label htmlFor={inputId} className="block text-xs font-semibold text-[#475569]">
            {label}
          </label>
        )}
        <div className="relative flex items-center">
          {leftIcon && (
            <div className="absolute left-3.5 flex items-center pointer-events-none text-[#64748B]">
              {leftIcon}
            </div>
          )}
          <input
            id={inputId}
            ref={ref}
            className={cn(
              'w-full bg-white text-[#0F172A] placeholder-[#64748B] text-sm rounded-xl border border-[#E2E8F0] hover:border-[#CBD5E1] px-4 py-2.5 transition-all duration-200 outline-none focus:border-[#14B8A6] focus:ring-2 focus:ring-[#14B8A6]/20 shadow-xs',
              leftIcon && 'pl-10',
              rightElement && 'pr-12',
              error && 'border-[#E11D48] focus:border-[#E11D48] focus:ring-[#E11D48]/20',
              className
            )}
            {...props}
          />
          {rightElement && (
            <div className="absolute right-2.5 flex items-center">
              {rightElement}
            </div>
          )}
        </div>
        {error ? (
          <p className="text-xs text-[#E11D48] font-medium pl-1">{error}</p>
        ) : helperText ? (
          <p className="text-xs text-[#64748B] pl-1">{helperText}</p>
        ) : null}
      </div>
    )
  }
)

Input.displayName = 'Input'
