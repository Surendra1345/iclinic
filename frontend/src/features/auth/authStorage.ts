const TOKEN_KEY = 'iclinic.frontdesk.token'

/** The login token lives in sessionStorage, so closing the tab logs the front desk out. */
export const authStorage = {
  getToken(): string | null {
    try {
      return window.sessionStorage.getItem(TOKEN_KEY)
    } catch {
      return null
    }
  },
  setToken(token: string): void {
    try {
      window.sessionStorage.setItem(TOKEN_KEY, token)
    } catch {
      /* storage can be blocked; the user simply has to log in again */
    }
  },
  clear(): void {
    try {
      window.sessionStorage.removeItem(TOKEN_KEY)
    } catch {
      /* ignore */
    }
  },
}
