import React, { useState, useRef, useEffect } from 'react'
import {
  Bot,
  User,
  Mic,
  PhoneCall,
  Calendar,
  Stethoscope,
  MapPin,
  CheckCircle2,
  Sparkles,
  ArrowUp,
  LayoutDashboard,
  RotateCcw,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { CallModal } from './components/CallModal'
import { VoiceOverlay } from './components/VoiceOverlay'
import { useSendChatMessage } from './queries/patientQueries'
import { ENV } from '../../config/env'
import type { ChatMessage } from '../../types'

export const ChatGPTStylePatientView: React.FC = () => {
  const [inputText, setInputText] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isCallModalOpen, setIsCallModalOpen] = useState(false)
  const [isVoiceOverlayOpen, setIsVoiceOverlayOpen] = useState(false)
  const [sessionId, setSessionId] = useState<string>(() => `chat_${crypto.randomUUID()}`)

  const chatMutation = useSendChatMessage()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, chatMutation.isPending])

  const handleSendMessage = async (textToSend?: string) => {
    const text = (textToSend || inputText).trim()
    if (!text || chatMutation.isPending) return

    const userMsg: ChatMessage = {
      id: `u_${Date.now()}`,
      sender: 'patient',
      text,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    }

    setMessages((prev) => [...prev, userMsg])
    setInputText('')

    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }

    try {
      const response = await chatMutation.mutateAsync({
        message: text,
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
    } catch {
      const fallbackMsg: ChatMessage = {
        id: `err_${Date.now()}`,
        sender: 'assistant',
        text: 'I apologize, I encountered an issue contacting the scheduling server. Please try again or use the Call tag to receive a phone call.',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }
      setMessages((prev) => [...prev, fallbackMsg])
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSendMessage()
    }
  }

  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInputText(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`
  }

  const startNewChat = () => {
    setSessionId(`chat_${Date.now()}_${crypto.randomUUID()}`)
    setMessages([])
    setInputText('')
  }


  return (
    <div className="flex flex-col h-screen bg-[#F6F9FB] text-[#0F172A] selection:bg-[#CCFBF1] selection:text-[#0F766E]">
      {/* Top ChatGPT / Gemini style Header Bar */}
      <header className="h-14 border-b border-[#E2E8F0] bg-white/90 backdrop-blur-md px-4 sm:px-6 flex items-center justify-between shrink-0 z-20">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-[#14B8A6] flex items-center justify-center text-white font-bold shadow-sm">
            <Stethoscope className="w-4 h-4 text-white" />
          </div>
          <span className="font-semibold text-[#0F172A] tracking-tight text-sm sm:text-base">
            {ENV.CLINIC_NAME}
          </span>

          {/* Quick Mode Tags (Chat, Voice, Call) */}
          <div className="hidden sm:flex items-center gap-2 ml-4 pl-4 border-l border-[#E2E8F0]">
            <button
              type="button"
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-[#CCFBF1] text-[#0D9488] border border-[#99F6E4]"
            >
              <Sparkles className="w-3 h-3 text-[#0D9488]" />
              <span>Chat</span>
            </button>

            <button
              type="button"
              onClick={() => setIsVoiceOverlayOpen(true)}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-[#E0E7FF] text-[#6366F1] hover:bg-[#EEF2FF] border border-[#C7D2FE] transition-colors cursor-pointer"
            >
              <Mic className="w-3 h-3 text-[#6366F1]" />
              <span>Voice</span>
            </button>

            <button
              type="button"
              onClick={() => setIsCallModalOpen(true)}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-[#E0F2FE] text-[#0284C7] hover:bg-[#F0F9FF] border border-[#BAE6FD] transition-colors cursor-pointer"
            >
              <PhoneCall className="w-3 h-3 text-[#0284C7]" />
              <span>Call</span>
            </button>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {messages.length > 0 && (
            <button
              type="button"
              onClick={startNewChat}
              className="text-xs text-[#475569] hover:text-[#0F172A] flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg hover:bg-[#F1F5F9] transition-colors cursor-pointer"
              title="New Chat"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">New Chat</span>
            </button>
          )}

          <Link
            to="/frontdesk"
            className="flex items-center gap-1.5 text-xs font-medium text-[#475569] hover:text-[#0F766E] px-3 py-1.5 rounded-lg bg-white border border-[#E2E8F0] hover:border-[#14B8A6] transition-all shadow-sm"
          >
            <LayoutDashboard className="w-3.5 h-3.5 text-[#14B8A6]" />
            <span>Frontdesk Console</span>
          </Link>
        </div>
      </header>

      {/* Main Conversation Canvas */}
      <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-6">
        <div className="max-w-3xl mx-auto h-full flex flex-col justify-between">
          {/* Welcome Screen when no messages */}
          {messages.length === 0 ? (
            <div className="my-auto text-center space-y-8 py-10 animate-fadeIn">
              <div className="space-y-3">
                <div className="inline-flex p-3 rounded-2xl bg-[#CCFBF1] border border-[#99F6E4] text-[#0D9488] mb-1 shadow-sm">
                  <Sparkles className="w-7 h-7" />
                </div>
                <h1 className="text-3xl sm:text-4xl font-semibold text-[#0F172A] tracking-tight">
                  How can I help you today?
                </h1>
                <p className="text-sm sm:text-base text-[#475569] max-w-lg mx-auto">
                  Ask me about doctor availability, book or reschedule an appointment, or request an instant voice call.
                </p>
              </div>
            </div>
          ) : (
            /* Message Feed */
            <div className="space-y-6 pb-6">
              {messages.map((msg) => (
                <div
                  key={msg.id}
                  className={`flex items-start gap-3.5 ${
                    msg.sender === 'patient' ? 'justify-end' : 'justify-start'
                  }`}
                >
                  {msg.sender === 'assistant' && (
                    <div className="w-8 h-8 rounded-xl bg-[#CCFBF1] text-[#0D9488] flex items-center justify-center shrink-0 border border-[#99F6E4] mt-0.5 shadow-sm">
                      <Bot className="w-4.5 h-4.5" />
                    </div>
                  )}

                  <div
                    className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                      msg.sender === 'patient'
                        ? 'bg-[#0F766E] text-white rounded-tr-none shadow-sm'
                        : 'bg-white border border-[#E2E8F0] text-[#0F172A] rounded-tl-none shadow-[var(--shadow-card)]'
                    }`}
                  >
                    <p className="whitespace-pre-wrap">{msg.text}</p>

                    {/* Target Slot Details Card */}
                    {msg.targetSlot && (
                      <div className="mt-3 p-3 rounded-xl bg-[#F8FAFC] border border-[#E2E8F0] text-xs text-[#475569] space-y-1.5">
                        <div className="flex items-center justify-between text-[#0F766E] font-semibold border-b border-[#E2E8F0] pb-1.5">
                          <span className="flex items-center gap-1.5">
                            <Calendar className="w-3.5 h-3.5 text-[#0D9488]" />
                            Appointment Details
                          </span>
                          {msg.isConfirmed && (
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-[#D1FAE5] text-[#059669] border border-[#A7F3D0]">
                              Confirmed
                            </span>
                          )}
                        </div>
                        {msg.targetSlot.doctor_name && (
                          <p className="flex items-center gap-1.5">
                            <Stethoscope className="w-3.5 h-3.5 text-[#64748B] shrink-0" />
                            <span>Doctor: <strong className="text-[#0F172A]">{msg.targetSlot.doctor_name}</strong></span>
                          </p>
                        )}
                        {msg.targetSlot.location_name && (
                          <p className="flex items-center gap-1.5">
                            <MapPin className="w-3.5 h-3.5 text-[#64748B] shrink-0" />
                            <span>Location: {msg.targetSlot.location_name}</span>
                          </p>
                        )}
                      </div>
                    )}

                    {msg.isConfirmed && (
                      <div className="mt-2 flex items-center gap-1.5 text-xs text-[#059669] font-medium">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>Saved to clinic database.</span>
                      </div>
                    )}
                  </div>

                  {msg.sender === 'patient' && (
                    <div className="w-8 h-8 rounded-xl bg-[#CCFBF1] text-[#0F766E] flex items-center justify-center shrink-0 border border-[#99F6E4] mt-0.5 shadow-sm">
                      <User className="w-4.5 h-4.5" />
                    </div>
                  )}
                </div>
              ))}

              {chatMutation.isPending && (
                <div className="flex items-start gap-3.5">
                  <div className="w-8 h-8 rounded-xl bg-[#CCFBF1] text-[#0D9488] flex items-center justify-center shrink-0 border border-[#99F6E4] animate-pulse">
                    <Bot className="w-4.5 h-4.5" />
                  </div>
                  <div className="bg-white border border-[#E2E8F0] rounded-2xl rounded-tl-none px-4 py-3 text-sm text-[#0D9488] flex items-center gap-2 shadow-[var(--shadow-card)]">
                    <span className="w-2 h-2 rounded-full bg-[#14B8A6] animate-bounce" />
                    <span className="w-2 h-2 rounded-full bg-[#14B8A6] animate-bounce [animation-delay:0.2s]" />
                    <span className="w-2 h-2 rounded-full bg-[#14B8A6] animate-bounce [animation-delay:0.4s]" />
                    <span className="text-xs text-[#64748B] ml-1">Looking up clinic schedules...</span>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          )}
        </div>
      </div>

      {/* Bottom Floating Prompt Bar */}
      <div className="shrink-0 p-4 sm:p-6 bg-gradient-to-t from-[#F6F9FB] via-[#F6F9FB] to-transparent">
        <div className="max-w-3xl mx-auto">
          <div className="relative flex items-end gap-2 bg-white border border-[#CBD5E1] rounded-3xl p-2 sm:p-2.5 shadow-[var(--shadow-card)] focus-within:border-[#14B8A6] focus-within:ring-2 focus-within:ring-[#14B8A6]/20 transition-all">
            {/* Auto-growing Textarea */}
            <textarea
              ref={textareaRef}
              rows={1}
              value={inputText}
              onChange={handleTextareaChange}
              onKeyDown={handleKeyDown}
              placeholder="Ask anything about doctors, branches, or book an appointment..."
              className="flex-1 bg-transparent text-[#0F172A] placeholder-[#64748B] text-sm sm:text-base px-3 py-2 outline-none resize-none max-h-36 min-h-[38px] leading-relaxed"
            />

            {/* Embedded Action Tags: Voice, Call, Send */}
            <div className="flex items-center gap-1.5 shrink-0 pb-0.5 pr-1">
              {/* Voice Tag */}
              <button
                type="button"
                onClick={() => setIsVoiceOverlayOpen(true)}
                className="p-2 sm:px-3 sm:py-1.5 rounded-full text-[#6366F1] hover:text-[#4338CA] bg-[#E0E7FF] hover:bg-[#EEF2FF] border border-[#C7D2FE] transition-all flex items-center gap-1.5 text-xs font-semibold cursor-pointer shadow-sm"
                title="Voice Assistant Mode"
              >
                <Mic className="w-4 h-4 text-[#6366F1]" />
                <span className="hidden sm:inline">Voice</span>
              </button>

              {/* Call Tag */}
              <button
                type="button"
                onClick={() => setIsCallModalOpen(true)}
                className="p-2 sm:px-3 sm:py-1.5 rounded-full text-[#0284C7] hover:text-[#0369A1] bg-[#E0F2FE] hover:bg-[#BAE6FD] border border-[#BAE6FD] transition-all flex items-center gap-1.5 text-xs font-semibold cursor-pointer shadow-sm"
                title="Request Outbound Phone Callback"
              >
                <PhoneCall className="w-4 h-4 text-[#0284C7]" />
                <span className="hidden sm:inline">Call</span>
              </button>

              {/* Send Button */}
              <button
                type="button"
                onClick={() => handleSendMessage()}
                disabled={!inputText.trim() || chatMutation.isPending}
                className="w-9 h-9 rounded-full bg-[#0F766E] hover:bg-[#0D9488] text-white flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed shadow-sm transition-all cursor-pointer"
                title="Send Message"
              >
                <ArrowUp className="w-4 h-4" />
              </button>
            </div>
          </div>

          <p className="text-[11px] text-[#64748B] text-center mt-2">
            City Care AI assistant can make mistakes. For medical emergencies, dial{' '}
            <strong className="font-bold text-[#DC2626]">108</strong> immediately.
          </p>
        </div>
      </div>

      {/* Voice Mode Overlay */}
      <VoiceOverlay
        isOpen={isVoiceOverlayOpen}
        onClose={() => setIsVoiceOverlayOpen(false)}
        sessionId={sessionId}
        onNewMessage={(msg) => setMessages((prev) => [...prev, msg])}
      />

      {/* Call Me Outbound Callback Modal */}
      <CallModal
        isOpen={isCallModalOpen}
        onClose={() => setIsCallModalOpen(false)}
      />
    </div>
  )
}
