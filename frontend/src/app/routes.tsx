import React from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { ChatGPTStylePatientView } from '../features/patient/ChatGPTStylePatientView'
import { FrontdeskPage } from '../features/frontdesk/FrontdeskPage'

export const AppRoutes: React.FC = () => {
  return (
    <Routes>
      {/* Patient Experience Route */}
      <Route path="/patients" element={<ChatGPTStylePatientView />} />

      {/* Frontdesk Operations Route */}
      <Route path="/frontdesk" element={<FrontdeskPage />} />

      {/* Redirect root to /patients */}
      <Route path="/" element={<Navigate to="/patients" replace />} />

      {/* Catch-all redirect */}
      <Route path="*" element={<Navigate to="/patients" replace />} />
    </Routes>
  )
}
