import React from 'react'
import { Navigate } from 'react-router-dom'
import { authService } from './authService'

/** Sends anyone without a front desk login to the login page. */
export const RequireAuth: React.FC<{ children: React.ReactElement }> = ({ children }) => {
  if (!authService.isLoggedIn()) {
    return <Navigate to="/frontdesk/login" replace />
  }
  return children
}
