import { apiClient } from '../../../lib/axios'
import type {
  AppointmentRecord,
  ClinicLocation,
  ConversationDetail,
  ConversationSummary,
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

export interface ConversationFilters {
  channel?: string
  search?: string
  state?: string
  outcome?: string
  confirmation_status?: string
  date_from?: string
  date_to?: string
  sort?: string
  order?: string
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
    channel?: string
    date_from?: string
    date_to?: string
    provider?: string
    appointment_type?: string
    confirmation_status?: string
    sort?: string
    order?: string
  }): Promise<AppointmentListResponse> {
    const response = await apiClient.get<AppointmentListResponse>(
      '/api/dashboard/appointments',
      { params }
    )
    return response.data
  },

  /**
   * Fetches conversation records (chat, voice, outbound call) with filters and sorting.
   */
  async getConversations(params?: ConversationFilters): Promise<{ conversations: ConversationSummary[]; total: number }> {
    const response = await apiClient.get<{ conversations: ConversationSummary[]; total: number }>(
      '/api/dashboard/conversations',
      { params }
    )
    return response.data
  },

  /**
   * Fetches one conversation with its transcript, state timeline, and step log.
   */
  async getConversationDetail(id: string): Promise<ConversationDetail> {
    const response = await apiClient.get<ConversationDetail>(`/api/dashboard/conversations/${id}`)
    return response.data
  },

  /**
   * Fetches the active appointment type names for the filters.
   */
  async getAppointmentTypes(): Promise<string[]> {
    const response = await apiClient.get<{ appointment_types: string[] }>('/api/dashboard/appointment-types')
    return response.data.appointment_types
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

