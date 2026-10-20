import React, { useState } from 'react'
import { Navbar, type MainViewType } from '../components/common/Navbar'
import { Footer } from '../components/common/Footer'
import { PatientView } from '../features/patient/PatientView'
import { FrontdeskView } from '../features/frontdesk/FrontdeskView'

export const MainLayout: React.FC = () => {
  const [currentView, setCurrentView] = useState<MainViewType>('patient')

  return (
    <div className="min-h-screen flex flex-col bg-[#070b14] text-slate-100 selection:bg-teal-500/30 selection:text-teal-200">
      <Navbar currentView={currentView} onViewChange={setCurrentView} />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {currentView === 'patient' ? <PatientView /> : <FrontdeskView />}
      </main>

      <Footer />
    </div>
  )
}
