import React from 'react'
import { cn } from '../../lib/utils'

interface AudioWaveVisualizerProps {
  isActive: boolean
  isSpeaking?: boolean
  className?: string
  barCount?: number
}

export const AudioWaveVisualizer: React.FC<AudioWaveVisualizerProps> = ({
  isActive,
  isSpeaking = false,
  className,
  barCount = 18,
}) => {
  const bars = Array.from({ length: barCount }, (_, i) => i)

  return (
    <div
      className={cn(
        'flex items-center justify-center gap-1.5 h-16 px-6 py-2 rounded-2xl bg-slate-950/60 border border-slate-800/80 transition-all duration-300',
        isActive && 'border-teal-500/40 shadow-lg shadow-teal-500/10',
        className
      )}
    >
      {bars.map((bar) => {
        // Vary heights and animation delays to create an organic audio wave
        const delay = (bar * 0.08) % 1.2
        const randomHeightMultiplier = 0.4 + ((bar * 7) % 10) * 0.06

        return (
          <div
            key={bar}
            className={cn(
              'w-1 rounded-full transition-all duration-200',
              isActive
                ? isSpeaking
                  ? 'bg-gradient-to-t from-teal-400 to-cyan-300'
                  : 'bg-gradient-to-t from-emerald-400 to-teal-300'
                : 'bg-slate-700/60 h-2'
            )}
            style={{
              height: isActive ? `${Math.max(8, 36 * randomHeightMultiplier)}px` : '4px',
              animation: isActive ? `audio-bar 1.1s ease-in-out infinite` : 'none',
              animationDelay: `${delay}s`,
            }}
          />
        )
      })}
    </div>
  )
}
