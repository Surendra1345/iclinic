import React from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { ChatGPTStylePatientView } from '../features/patient/ChatGPTStylePatientView'
import { FrontdeskPage } from '../features/frontdesk/FrontdeskPage'
import { LoginPage } from '../features/auth/LoginPage'
import { RequireAuth } from '../features/auth/RequireAuth'

export const AppRoutes: React.FC = () => {
  return (
    <Routes>
      {/* Patient Experience Route */}
      <Route path="/patients" element={<ChatGPTStylePatientView />} />

      {/* Frontdesk login and operations (login required) */}
      <Route path="/frontdesk/login" element={<LoginPage />} />
      <Route
        path="/frontdesk"
        element={
          <RequireAuth>
            <FrontdeskPage />
          </RequireAuth>
        }
      />

      {/* Redirect root to /patients */}
      <Route path="/" element={<Navigate to="/patients" replace />} />

      {/* Catch-all redirect */}
      <Route path="*" element={<Navigate to="/patients" replace />} />
    </Routes>
  )
}
