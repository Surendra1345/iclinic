import React, { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { ArrowLeft, Lock, Mail, Stethoscope } from 'lucide-react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Input } from '../../components/ui/Input'
import { ENV } from '../../config/env'
import { authService } from './authService'

export const LoginPage: React.FC = () => {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  if (authService.isLoggedIn()) {
    return <Navigate to="/frontdesk" replace />
  }

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError('')
    setIsSubmitting(true)
    try {
      await authService.login(email.trim(), password)
      navigate('/frontdesk', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not log in. Please try again.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#F6F9FB] flex items-center justify-center px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="flex flex-col items-center gap-3 text-center">
          <div className="w-12 h-12 rounded-2xl bg-[#14B8A6] flex items-center justify-center shadow-sm">
            <Stethoscope className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-[#0F172A] tracking-tight">{ENV.CLINIC_NAME}</h1>
            <p className="text-sm text-[#475569]">Front desk sign in</p>
          </div>
        </div>

        <Card>
          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            <Input
              label="Email"
              type="email"
              autoComplete="username"
              placeholder="you@clinic.com"
              leftIcon={<Mail className="w-4 h-4" />}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
            />
            <Input
              label="Password"
              type="password"
              autoComplete="current-password"
              placeholder="Your password"
              leftIcon={<Lock className="w-4 h-4" />}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />

            {error && (
              <p role="alert" className="text-xs font-medium text-[#E11D48] bg-[#FFE4E6] border border-[#FECDD3] rounded-xl px-3 py-2">
                {error}
              </p>
            )}

            <Button type="submit" className="w-full" isLoading={isSubmitting} disabled={!email || !password}>
              Sign in
            </Button>
          </form>
        </Card>

        <div className="text-center">
          <Link
            to="/patients"
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#475569] hover:text-[#0F172A]"
          >
            <ArrowLeft className="w-3.5 h-3.5 text-[#0D9488]" />
            Back to the patient experience
          </Link>
        </div>
      </div>
    </div>
  )
}
