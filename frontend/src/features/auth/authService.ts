import { apiClient } from '../../lib/axios'
import { authStorage } from './authStorage'

export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
  email: string
}

export const authService = {
  async login(email: string, password: string): Promise<LoginResponse> {
    const response = await apiClient.post<LoginResponse>('/api/auth/login', { email, password })
    authStorage.setToken(response.data.access_token)
    return response.data
  },

  logout(): void {
    authStorage.clear()
  },

  isLoggedIn(): boolean {
    return Boolean(authStorage.getToken())
  },
}
