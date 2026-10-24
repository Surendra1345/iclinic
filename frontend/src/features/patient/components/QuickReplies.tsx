import React from 'react'
import type { SlotOption } from '../../../types'

interface QuickRepliesProps {
  options?: SlotOption[]
  /** Only the assistant's latest message is still waiting for an answer. */
  isLatest: boolean
  disabled?: boolean
  onSelect: (message: string) => void
}

/** Tap-to-answer buttons under an assistant message; tapping one sends the same words the patient could type. */
export const QuickReplies: React.FC<QuickRepliesProps> = ({ options, isLatest, disabled, onSelect }) => {
  if (!isLatest || !options || options.length === 0) return null
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {options.map((option) => (
        <button
          key={option.message}
          type="button"
          disabled={disabled}
          onClick={() => onSelect(option.message)}
          className="px-3 py-1.5 rounded-full text-xs font-semibold border border-[#99F6E4] bg-[#F0FDFA] text-[#0F766E] hover:bg-[#CCFBF1] disabled:opacity-50 transition-colors cursor-pointer"
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
