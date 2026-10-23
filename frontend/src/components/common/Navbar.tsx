import React from 'react'
import {
  Stethoscope,
  PhoneCall,
  LayoutDashboard,
} from 'lucide-react'
import { Badge } from '../ui/Badge'
import { ENV } from '../../config/env'

export type MainViewType = 'patient' | 'frontdesk'

interface NavbarProps {
  currentView: MainViewType
  onViewChange: (view: MainViewType) => void
}

export const Navbar: React.FC<NavbarProps> = ({ currentView, onViewChange }) => {
  return (
    <header className="sticky top-0 z-50 w-full border-b border-[#E2E8F0] bg-white/95 backdrop-blur-md shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
        {/* Brand Logo & Name */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-[#14B8A6] flex items-center justify-center text-white shadow-sm font-bold">
            <Stethoscope className="w-5 h-5 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-[#0F172A] text-base sm:text-lg tracking-tight">
                {ENV.CLINIC_NAME}
              </span>
              <span className="hidden sm:inline-block">
                <Badge variant="teal" className="text-[10px] py-0.5">
                  AI Voice & Web
                </Badge>
              </span>
            </div>
            <p className="text-[11px] text-[#64748B] hidden sm:block">
              Intelligent Multi-Branch Appointment Scheduling
            </p>
          </div>
        </div>

        {/* View Switcher: Patient Portal vs Frontdesk Dashboard */}
        <div className="flex items-center gap-1.5 p-1 rounded-xl bg-[#F1F5F9] border border-[#E2E8F0]">
          <button
            type="button"
            onClick={() => onViewChange('patient')}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all duration-200 cursor-pointer ${
              currentView === 'patient'
                ? 'bg-[#0F766E] text-white shadow-sm'
                : 'text-[#475569] hover:text-[#0F172A] hover:bg-white'
            }`}
          >
            <PhoneCall className="w-3.5 h-3.5" />
            <span>Patient Portal</span>
          </button>

          <button
            type="button"
            onClick={() => onViewChange('frontdesk')}
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all duration-200 cursor-pointer ${
              currentView === 'frontdesk'
                ? 'bg-[#0F766E] text-white shadow-sm'
                : 'text-[#475569] hover:text-[#0F172A] hover:bg-white'
            }`}
          >
            <LayoutDashboard className="w-3.5 h-3.5" />
            <span>Frontdesk Dashboard</span>
          </button>
        </div>

        {/* Live System Indicator */}
        <div className="hidden lg:flex items-center gap-2.5">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-[#D1FAE5] border border-[#A7F3D0] text-[#059669] text-xs font-medium">
            <span className="w-2 h-2 rounded-full bg-[#059669] animate-pulse" />
            <span>AI Voice Gateway Active</span>
          </div>
        </div>
      </div>
    </header>
  )
}
