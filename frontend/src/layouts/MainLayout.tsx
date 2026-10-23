import React, { useState } from 'react'
import { Navbar, type MainViewType } from '../components/common/Navbar'
import { Footer } from '../components/common/Footer'
import { PatientView } from '../features/patient/PatientView'
import { FrontdeskView } from '../features/frontdesk/FrontdeskView'

export const MainLayout: React.FC = () => {
  const [currentView, setCurrentView] = useState<MainViewType>('patient')

  return (
    <div className="min-h-screen flex flex-col bg-[#F6F9FB] text-[#0F172A] selection:bg-[#CCFBF1] selection:text-[#0F766E]">
      <Navbar currentView={currentView} onViewChange={setCurrentView} />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {currentView === 'patient' ? <PatientView /> : <FrontdeskView />}
      </main>

      <Footer />
    </div>
  )
}
