import React, { useState, useRef, useEffect } from 'react'
import { Send, Bot, User, Sparkles, CheckCircle2, RotateCcw, Calendar, MapPin, Stethoscope, Mail } from 'lucide-react'
import { Card } from '../../../components/ui/Card'
import { Button } from '../../../components/ui/Button'
import { Badge } from '../../../components/ui/Badge'
import { PATIENT_PROMPT_PRESETS } from '../../../config/constants'
import { useSendChatMessage } from '../queries/patientQueries'
import { ENV } from '../../../config/env'
import type { ChatMessage } from '../../../types'

export const ChatTab: React.FC = () => {
  const [inputText, setInputText] = useState('')
  const [patientName, setPatientName] = useState('')
  const [patientEmail, setPatientEmail] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      sender: 'assistant',
      text: `Hello! Welcome to ${ENV.CLINIC_NAME}. How can I help you today? You can ask me to book, reschedule, cancel, or ask for available doctors and branches.`,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    },
  ])
  const [sessionId, setSessionId] = useState<string>(() => `chat_${crypto.randomUUID()}`)

  const chatMutation = useSendChatMessage()
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, chatMutation.isPending])

  const handleSendMessage = async (textToSend?: string) => {
    const message = (textToSend || inputText).trim()
    if (!message || chatMutation.isPending) return

    const userMsg: ChatMessage = {
      id: `u_${Date.now()}`,
      sender: 'patient',
      text: message,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    }

    setMessages((prev) => [...prev, userMsg])
    setInputText('')

    try {
      const response = await chatMutation.mutateAsync({
        message,
        patient_name: patientName.trim() || undefined,
        patient_phone: ENV.DEFAULT_PHONE || undefined,
        patient_email: patientEmail.trim() || undefined,
        session_id: sessionId,
      })

      const botMsg: ChatMessage = {
        id: `a_${Date.now()}`,
        sender: 'assistant',
        text: response.reply,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        targetSlot: response.target_slot,
        isConfirmed: response.booking_confirmed,
      }

      setMessages((prev) => [...prev, botMsg])
    } catch (err: any) {
      const errMsg: ChatMessage = {
        id: `err_${Date.now()}`,
        sender: 'assistant',
        text: 'Sorry, I encountered an issue connecting to the scheduling system. Please verify the backend is active.',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }
      setMessages((prev) => [...prev, errMsg])
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSendMessage()
    }
  }

  const resetChat = () => {
    setSessionId(`chat_${Date.now()}_${crypto.randomUUID()}`)
    setInputText('')
    setMessages([
      {
        id: 'reset',
        sender: 'assistant',
        text: `Chat session reset. How can I assist you with your clinic visit?`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      },
    ])
  }

  return (
    <div className="max-w-4xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2">
            Clinic Assistant Chat
            <Badge variant="teal">Online</Badge>
          </h2>
          <p className="text-xs sm:text-sm text-slate-400">
            Intelligent conversation engine powered by clinical decision graph
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={resetChat}
          leftIcon={<RotateCcw className="w-3.5 h-3.5" />}
        >
          Clear Chat
        </Button>
      </div>

      {/* Preset Suggestion Chips */}
      <div className="space-y-1.5">
        <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
          <Sparkles className="w-3 h-3 text-teal-400" /> Instant Prompt Presets
        </span>
        <div className="flex flex-wrap gap-2">
          {PATIENT_PROMPT_PRESETS.map((preset, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => handleSendMessage(preset.text)}
              className="text-xs px-3 py-1.5 rounded-full bg-slate-900/90 text-slate-300 hover:text-white border border-slate-800 hover:border-teal-500/50 hover:bg-slate-800 transition-all text-left shadow-sm cursor-pointer"
            >
              <span className="text-teal-400/80 mr-1.5 font-medium">{preset.category}:</span>
              {preset.text}
            </button>
          ))}
        </div>
      </div>

      {/* Chat Messages Container */}
      <Card glow="teal" className="p-4 sm:p-6 space-y-4">
        <div className="h-[420px] overflow-y-auto space-y-4 pr-1">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex items-start gap-3 ${
                msg.sender === 'patient' ? 'justify-end' : 'justify-start'
              }`}
            >
              {msg.sender === 'assistant' && (
                <div className="w-8 h-8 rounded-xl bg-teal-500/20 text-teal-300 flex items-center justify-center shrink-0 border border-teal-500/30 shadow-md">
                  <Bot className="w-4.5 h-4.5" />
                </div>
              )}

              <div
                className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                  msg.sender === 'patient'
                    ? 'bg-gradient-to-r from-teal-600 to-emerald-600 text-white rounded-tr-none shadow-md'
                    : 'bg-slate-900 border border-slate-800 text-slate-200 rounded-tl-none shadow-inner'
                }`}
              >
                <div className="flex items-center justify-between gap-4 mb-1 text-[11px] opacity-70">
                  <span className="font-semibold">
                    {msg.sender === 'patient' ? 'You' : 'Dr. Care Assistant'}
                  </span>
                  <span>{msg.timestamp}</span>
                </div>
                <p className="whitespace-pre-wrap">{msg.text}</p>

                {/* Slot Details Card if returned */}
                {msg.targetSlot && (
                  <div className="mt-3 p-3 rounded-xl bg-slate-950/80 border border-teal-500/30 text-xs text-slate-300 space-y-1.5">
                    <div className="flex items-center justify-between text-teal-300 font-semibold border-b border-slate-800 pb-1.5">
                      <span className="flex items-center gap-1.5">
                        <Calendar className="w-3.5 h-3.5 text-teal-400" />
                        Scheduled Appointment Slot
                      </span>
                      {msg.isConfirmed && (
                        <Badge variant="emerald" className="text-[10px] py-0.5">
                          Confirmed
                        </Badge>
                      )}
                    </div>
                    {msg.targetSlot.doctor_name && (
                      <p className="flex items-center gap-1.5">
                        <Stethoscope className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                        <span>Doctor: <strong>{msg.targetSlot.doctor_name}</strong></span>
                      </p>
                    )}
                    {msg.targetSlot.location && (
                      <p className="flex items-center gap-1.5">
                        <MapPin className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                        <span>Branch: {msg.targetSlot.location}</span>
                      </p>
                    )}
                  </div>
                )}

                {msg.isConfirmed && (
                  <div className="mt-2 flex items-center gap-1.5 text-xs text-emerald-400 font-medium">
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    <span>Appointment logged to clinical database.</span>
                  </div>
                )}
              </div>

              {msg.sender === 'patient' && (
                <div className="w-8 h-8 rounded-xl bg-emerald-500/20 text-emerald-300 flex items-center justify-center shrink-0 border border-emerald-500/30 shadow-md">
                  <User className="w-4.5 h-4.5" />
                </div>
              )}
            </div>
          ))}

          {chatMutation.isPending && (
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-xl bg-teal-500/20 text-teal-300 flex items-center justify-center shrink-0 border border-teal-500/30 animate-pulse">
                <Bot className="w-4.5 h-4.5" />
              </div>
              <div className="bg-slate-900 border border-slate-800 rounded-2xl rounded-tl-none px-4 py-3 text-sm text-teal-300 flex items-center gap-2 shadow-inner">
                <span className="w-2 h-2 rounded-full bg-teal-400 animate-bounce" />
                <span className="w-2 h-2 rounded-full bg-teal-400 animate-bounce [animation-delay:0.2s]" />
                <span className="w-2 h-2 rounded-full bg-teal-400 animate-bounce [animation-delay:0.4s]" />
                <span className="text-xs text-slate-400 ml-1">Analyzing symptoms & doctor availability...</span>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Patient Profile / Contact Info (Optional for Registration) */}
        <div className="flex flex-wrap items-center gap-3 px-1 pt-2 border-t border-slate-800/80 text-xs text-slate-400">
          <div className="flex items-center gap-1.5 min-w-[170px] flex-1">
            <User className="w-3.5 h-3.5 text-teal-400 shrink-0" />
            <input
              type="text"
              value={patientName}
              onChange={(e) => setPatientName(e.target.value)}
              placeholder="Your Full Name (optional)"
              className="w-full bg-slate-900 border border-slate-800 focus:border-teal-400 rounded-lg px-2.5 py-1 text-xs text-slate-200 outline-none"
            />
          </div>
          <div className="flex items-center gap-1.5 min-w-[170px] flex-1">
            <Mail className="w-3.5 h-3.5 text-teal-400 shrink-0" />
            <input
              type="email"
              value={patientEmail}
              onChange={(e) => setPatientEmail(e.target.value)}
              placeholder="Email for confirmation receipt"
              className="w-full bg-slate-900 border border-slate-800 focus:border-teal-400 rounded-lg px-2.5 py-1 text-xs text-slate-200 outline-none"
            />
          </div>
        </div>

        {/* Input Bar */}
        <div className="flex items-center gap-2">
          <textarea
            rows={1}
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type your symptoms, preferred doctor, or requested time (Press Enter to send)..."
            className="flex-1 bg-slate-900/90 text-slate-100 placeholder-slate-500 text-sm rounded-xl border border-slate-700/80 px-4 py-3 outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-400/20 resize-none shadow-inner"
          />
          <Button
            type="button"
            variant="primary"
            size="md"
            onClick={() => handleSendMessage()}
            disabled={!inputText.trim() || chatMutation.isPending}
            className="shrink-0 h-11 px-4"
          >
            <Send className="w-4 h-4" />
          </Button>
        </div>
      </Card>
    </div>
  )
}
