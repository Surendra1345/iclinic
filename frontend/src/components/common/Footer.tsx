import React from 'react'
import { ShieldCheck, MapPin } from 'lucide-react'
import { ENV } from '../../config/env'

export const Footer: React.FC = () => {
  return (
    <footer className="w-full border-t border-slate-800/80 bg-slate-950/60 mt-16 py-8">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 space-y-4">
        <div className="flex flex-col md:flex-row items-center justify-between gap-4 text-xs text-slate-400">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-teal-400" />
            <span>{ENV.CLINIC_NAME} © 2026. HIPAA-Compliant AI Clinical Scheduling System.</span>
          </div>
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-1">
              <MapPin className="w-3.5 h-3.5 text-slate-500" />
              Branches: Anna Nagar • T. Nagar • Velachery • Tambaram
            </span>
          </div>
        </div>

        <div className="p-3 rounded-xl bg-slate-900/60 border border-slate-800 text-[11px] text-slate-400 text-center leading-relaxed">
          <strong className="text-rose-400">Medical Emergency Notice:</strong> This AI assistant is designed for appointment scheduling, rescheduling, and doctor information. If you are experiencing a life-threatening medical emergency, please dial 108 or 112 immediately.
        </div>
      </div>
    </footer>
  )
}
