/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#F0FDFA',
          100: '#CCFBF1',
          200: '#99F6E4',
          300: '#5EEAD4',
          400: '#2DD4BF',
          500: '#14B8A6',
          600: '#0D9488',
          700: '#0F766E',
          800: '#115E59',
          900: '#134E4A',
          950: '#042F2E',
        },
        clinic: {
          50: '#F0FDFA',
          100: '#CCFBF1',
          200: '#99F6E4',
          300: '#5EEAD4',
          400: '#2DD4BF',
          500: '#14B8A6',
          600: '#0D9488',
          700: '#0F766E',
          800: '#115E59',
          900: '#134E4A',
          950: '#042F2E',
        },
        surface: {
          base: '#F6F9FB',
          card: '#FFFFFF',
          subtle: '#F1F5F9',
        },
        border: {
          subtle: '#E2E8F0',
          strong: '#CBD5E1',
        },
        txt: {
          primary: '#0F172A',
          secondary: '#475569',
          muted: '#64748B',
        },
        status: {
          booked: '#059669',
          'booked-bg': '#D1FAE5',
          'booked-border': '#A7F3D0',
          rescheduled: '#B45309',
          'rescheduled-bg': '#FEF3C7',
          'rescheduled-border': '#FDE68A',
          cancelled: '#E11D48',
          'cancelled-bg': '#FFE4E6',
          'cancelled-border': '#FECDD3',
          escalated: '#EA580C',
          'escalated-bg': '#FFEDD5',
          'escalated-border': '#FED7AA',
          info: '#0284C7',
          'info-bg': '#E0F2FE',
          'info-border': '#BAE6FD',
        },
        channel: {
          chat: '#0D9488',
          'chat-bg': '#CCFBF1',
          voice: '#6366F1',
          'voice-bg': '#E0E7FF',
          call: '#0284C7',
          'call-bg': '#E0F2FE',
        },
      },
      boxShadow: {
        card: '0 1px 2px rgba(15, 23, 42, 0.04), 0 4px 12px rgba(15, 23, 42, 0.05)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'wave': 'wave 1.5s ease-in-out infinite',
      },
      keyframes: {
        wave: {
          '0%, 100%': { transform: 'scaleY(0.4)' },
          '50%': { transform: 'scaleY(1.2)' },
        }
      }
    },
  },
  plugins: [],
}

