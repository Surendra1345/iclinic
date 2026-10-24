import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { frontdeskService, type ConversationFilters } from '../services/frontdeskService'

export const useDashboardStats = () => {
  return useQuery({
    queryKey: ['dashboard', 'stats'],
    queryFn: () => frontdeskService.getStats(),
    refetchInterval: 5000, // auto-refresh every 5s for real-time frontdesk monitoring
  })
}

export const useAppointments = (filters: {
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
}) => {
  return useQuery({
    queryKey: ['dashboard', 'appointments', filters],
    queryFn: () => frontdeskService.getAppointments(filters),
    refetchInterval: 5000,
  })
}

export const usePatients = (search?: string) => {
  return useQuery({
    queryKey: ['dashboard', 'patients', search],
    queryFn: () => frontdeskService.getPatients({ search }),
    refetchInterval: 5000,
  })
}

export const useClinicLocations = () => {
  return useQuery({
    queryKey: ['dashboard', 'locations'],
    queryFn: () => frontdeskService.getLocations(),
    staleTime: 1000 * 60, // 1 minute
  })
}

export const useForwardedRequests = (filters: { status?: string; search?: string }) => {
  return useQuery({
    queryKey: ['dashboard', 'forwarded_requests', filters],
    queryFn: () => frontdeskService.getForwardedRequests(filters),
    refetchInterval: 4000, // fast live sync for escalations
  })
}

export const useUpdateForwardedRequest = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string
      data: { status: 'pending' | 'contacted' | 'resolved'; notes?: string }
    }) => frontdeskService.updateForwardedRequest(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard', 'forwarded_requests'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard', 'stats'] })
    },
  })
}

export const useConversations = (filters: ConversationFilters) => {
  return useQuery({
    queryKey: ['dashboard', 'conversations', filters],
    queryFn: () => frontdeskService.getConversations(filters),
    refetchInterval: 5000,
  })
}

export const useConversationDetail = (id: string | null) => {
  return useQuery({
    queryKey: ['dashboard', 'conversation', id],
    queryFn: () => frontdeskService.getConversationDetail(id as string),
    enabled: Boolean(id),
    refetchInterval: 5000,
  })
}

export const useAppointmentTypes = () => {
  return useQuery({
    queryKey: ['dashboard', 'appointment_types'],
    queryFn: () => frontdeskService.getAppointmentTypes(),
    staleTime: 1000 * 60,
  })
}
