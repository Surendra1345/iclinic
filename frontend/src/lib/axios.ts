import axios from 'axios'
import { ENV } from '../config/env'
import { authStorage } from '../features/auth/authStorage'

/** One client for every API call. The front desk login token, when there is one, is sent with each request. */
export const apiClient = axios.create({
  baseURL: ENV.API_BASE_URL,
  timeout: 60_000,
})

apiClient.interceptors.request.use((config) => {
  const token = authStorage.getToken()
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const isLogin = String(error?.config?.url ?? '').includes('/api/auth/login')
    // An expired or invalid front desk token sends the user back to the login page.
    if (error?.response?.status === 401 && !isLogin && authStorage.getToken()) {
      authStorage.clear()
      window.location.assign('/frontdesk/login')
    }
    return Promise.reject(error)
  },
)
