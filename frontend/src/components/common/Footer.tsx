import React from 'react'
import { ShieldCheck, MapPin } from 'lucide-react'
import { ENV } from '../../config/env'

export const Footer: React.FC = () => {
  return (
    <footer className="w-full border-t border-[#E2E8F0] bg-white mt-16 py-8 text-[#475569]">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 space-y-4">
        <div className="flex flex-col md:flex-row items-center justify-between gap-4 text-xs text-[#64748B]">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-[#0D9488]" />
            <span>{ENV.CLINIC_NAME} © 2026. HIPAA-Compliant AI Clinical Scheduling System.</span>
          </div>
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-1">
              <MapPin className="w-3.5 h-3.5 text-[#64748B]" />
              Branches: Anna Nagar • T. Nagar • Velachery • Tambaram
            </span>
          </div>
        </div>

        <div className="p-3 rounded-xl bg-[#F1F5F9] border border-[#E2E8F0] text-[11px] text-[#64748B] text-center leading-relaxed">
          <strong className="text-[#0F172A]">Medical Emergency Notice:</strong> This AI assistant is designed for appointment scheduling, rescheduling, and doctor information. If you are experiencing a life-threatening medical emergency, please dial <strong className="text-[#DC2626] font-bold">108</strong> or 112 immediately.
        </div>
      </div>
    </footer>
  )
}
