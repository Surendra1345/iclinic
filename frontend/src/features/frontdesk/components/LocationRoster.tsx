import React from 'react'
import { Building2, MapPin } from 'lucide-react'
import { Card } from '../../../components/ui/Card'
import { Badge } from '../../../components/ui/Badge'
import { useClinicLocations } from '../queries/frontdeskQueries'

export const LocationRoster: React.FC = () => {
  const { data, isLoading } = useClinicLocations()
  const locations = data?.locations || []

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-white tracking-tight flex items-center gap-2">
            <Building2 className="w-5 h-5 text-teal-400" />
            Clinic Branch Network & Specialists
          </h3>
          <p className="text-xs text-slate-400">
            Current roster of medical providers across Chennai clinic locations
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {isLoading ? (
          Array.from({ length: 4 }).map((_, i) => (
            <Card key={i} className="animate-pulse h-48 bg-slate-900/60" />
          ))
        ) : (
          locations.map((loc) => (
            <Card key={loc.id} glow="none" className="p-5 flex flex-col justify-between space-y-4">
              <div>
                <div className="flex items-start justify-between gap-2">
                  <h4 className="font-semibold text-white text-base">{loc.name}</h4>
                  <Badge variant="teal" className="text-[10px]">
                    {loc.doctors.length} Doctors
                  </Badge>
                </div>
                <p className="text-xs text-slate-400 mt-1 flex items-start gap-1.5 leading-relaxed">
                  <MapPin className="w-3.5 h-3.5 text-slate-500 shrink-0 mt-0.5" />
                  <span>{loc.address}</span>
                </p>
              </div>

              <div className="pt-3 border-t border-slate-800/80 space-y-2">
                <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
                  Available Specialists
                </span>
                <div className="space-y-1.5">
                  {loc.doctors.map((doc) => (
                    <div
                      key={doc.id}
                      className="p-2 rounded-lg bg-slate-900/80 border border-slate-800 text-xs flex items-center justify-between"
                    >
                      <span className="font-medium text-slate-200 truncate pr-2">
                        {doc.full_name}
                      </span>
                      <span className="text-[11px] text-teal-400 bg-teal-500/10 px-2 py-0.5 rounded border border-teal-500/20 shrink-0">
                        {doc.specialty}
                      </span>
                    </div>
                  ))}
                  {loc.doctors.length === 0 && (
                    <p className="text-xs text-slate-500 italic">No doctors assigned</p>
                  )}
                </div>
              </div>
            </Card>
          ))
        )}
      </div>
    </div>
  )
}
