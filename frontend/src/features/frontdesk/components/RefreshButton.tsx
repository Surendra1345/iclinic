import React, { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { Button } from '../../../components/ui/Button'
import { formatClockIST } from '../../../lib/utils'

interface RefreshButtonProps {
  /** Reloads the data once and resolves when it has arrived. */
  onRefresh: () => Promise<unknown>
  /** When the data last arrived (react-query's dataUpdatedAt), shown next to the button. */
  updatedAt?: number
  label?: string
  className?: string
}

const formatTime = (timestamp: number) => formatClockIST(new Date(timestamp), true)

/**
 * One refresh button for every front desk table. It spins only while the request that the click
 * started is running, so the automatic 5-second refresh never makes it flicker or lock.
 */
export const RefreshButton: React.FC<RefreshButtonProps> = ({
  onRefresh,
  updatedAt,
  label = 'Refresh',
  className = '',
}) => {
  const [isRefreshing, setIsRefreshing] = useState(false)

  const handleClick = async () => {
    setIsRefreshing(true)
    try {
      await onRefresh()
    } finally {
      setIsRefreshing(false)
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Button
        type="button"
        variant="outline"
        size="md"
        className={`h-10 text-xs justify-center ${className}`}
        onClick={handleClick}
        disabled={isRefreshing}
        leftIcon={<RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />}
      >
        {isRefreshing ? 'Refreshing...' : label}
      </Button>
      {updatedAt ? (
        <span className="text-[11px] text-[#64748B] whitespace-nowrap" title="Time the data was last loaded">
          Updated {formatTime(updatedAt)}
        </span>
      ) : null}
    </div>
  )
}
