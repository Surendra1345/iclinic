import { apiClient } from '../../../lib/axios'
import type {
  AppointmentRecord,
  ClinicLocation,
  DashboardStats,
  ForwardedRequestsResponse,
} from '../../../types'

export interface AppointmentListResponse {
  appointments: AppointmentRecord[]
  total: number
}

export interface PatientListItem {
  id: string
  full_name: string
  phone: string
  email?: string
  date_of_birth?: string
  created_at?: string
  total_appointments: number
  active_appointment?: {
    appointment_id: string
    doctor_name: string
    specialty: string
    location_name: string
    start_time: string
    status: string
  } | null
}

export interface PatientListResponse {
  patients: PatientListItem[]
  total: number
}

export interface ClinicLocationsResponse {
  locations: ClinicLocation[]
}

export const frontdeskService = {
  /**
   * Fetches dashboard overview metrics (booked, rescheduled, cancelled, patients, etc.).
   */
  async getStats(): Promise<DashboardStats> {
    const response = await apiClient.get<DashboardStats>('/api/dashboard/stats')
    return response.data
  },

  /**
   * Fetches registered patients with active appointment info.
   */
  async getPatients(params?: { search?: string }): Promise<PatientListResponse> {
    const response = await apiClient.get<PatientListResponse>(
      '/api/dashboard/patients',
      { params }
    )
    return response.data
  },

  /**
   * Fetches appointment records with optional status, branch location, and search filters.
   */
  async getAppointments(params?: {
    status?: string
    location?: string
    search?: string
  }): Promise<AppointmentListResponse> {
    const response = await apiClient.get<AppointmentListResponse>(
      '/api/dashboard/appointments',
      { params }
    )
    return response.data
  },

  /**
   * Fetches clinic branch locations and provider rosters.
   */
  async getLocations(): Promise<ClinicLocationsResponse> {
    const response = await apiClient.get<ClinicLocationsResponse>(
      '/api/dashboard/locations'
    )
    return response.data
  },

  /**
   * Fetches patients whose conversations were forwarded to the front desk.
   */
  async getForwardedRequests(params?: {
    status?: string
    search?: string
  }): Promise<ForwardedRequestsResponse> {
    const response = await apiClient.get<ForwardedRequestsResponse>(
      '/api/dashboard/forwarded-requests',
      { params }
    )
    return response.data
  },

  /**
   * Updates escalation status ('pending' | 'contacted' | 'resolved') and optional staff notes.
   */
  async updateForwardedRequest(
    id: string,
    data: { status: 'pending' | 'contacted' | 'resolved'; notes?: string }
  ): Promise<{ status: string }> {
    const response = await apiClient.patch<{ status: string }>(
      `/api/dashboard/forwarded-requests/${id}`,
      data
    )
    return response.data
  },
}

