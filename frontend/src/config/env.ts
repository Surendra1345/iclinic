export const ENV = {
  API_BASE_URL: import.meta.env.VITE_API_BASE_URL || '',
  CLINIC_NAME: import.meta.env.VITE_CLINIC_NAME || 'City Care Clinic',
  DEFAULT_PHONE: import.meta.env.VITE_DEFAULT_PHONE || '',
  IS_DEV: import.meta.env.DEV,
}
