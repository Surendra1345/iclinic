import React, { useState, useEffect, useRef } from 'react'
import { Mic, MicOff, Volume2, Sparkles, AlertCircle, RotateCcw, Bot, User } from 'lucide-react'
import { Card } from '../../../components/ui/Card'
import { Button } from '../../../components/ui/Button'
import { Badge } from '../../../components/ui/Badge'
import { AudioWaveVisualizer } from '../../../components/common/AudioWaveVisualizer'
import { patientService } from '../services/patientService'
import { resolveVoiceAudioUrl, selectMaleSpeechVoice } from './selectMaleSpeechVoice'
import { ENV } from '../../../config/env'
import type { ChatMessage } from '../../../types'
import { formatClockIST } from '../../../lib/utils'

export const VoiceAssistantTab: React.FC = () => {
  const [isListening, setIsListening] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      sender: 'assistant',
      text: `Hello! Welcome to ${ENV.CLINIC_NAME}. How can I help you today?`,
      timestamp: formatClockIST(),
    },
  ])
  const [speechError, setSpeechError] = useState<string | null>(null)
  const [handsFreeMode, setHandsFreeMode] = useState<boolean>(true)
  const [userIsSpeaking, setUserIsSpeaking] = useState<boolean>(false)
  const [sessionId, setSessionId] = useState<string>(() => `voice_${Date.now()}`)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const handsFreeRef = useRef<boolean>(true)
  const audioContextRef = useRef<AudioContext | null>(null)
  const vadAnimationRef = useRef<number | null>(null)
  const hasDetectedSpeechRef = useRef<boolean>(false)
  const discardRecordingRef = useRef<boolean>(false)
  const isProcessingRef = useRef<boolean>(false)
  const startListeningRef = useRef<() => void>(() => {})

  handsFreeRef.current = handsFreeMode

  // Scroll to bottom on new message
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Create a browser voice session. The first greeting is always English;
  // Sarvam detects the patient's language from the first audio turn.
  useEffect(() => {
    patientService.createVoiceAssistantSession()
      .then((session) => {
        setSessionId(session.session_id)
        setMessages((previous) => previous.map((message, index) =>
          index === 0 ? { ...message, text: session.greeting } : message,
        ))
        speakAgentReply(session.greeting)
      })
      .catch(() => setSpeechError('Unable to start the voice assistant. Please try again.'))

    return () => {
      if (vadAnimationRef.current) {
        cancelAnimationFrame(vadAnimationRef.current)
      }
      if (audioContextRef.current) {
        try {
          audioContextRef.current.close().catch(() => {})
        } catch {}
      }
      if (window.speechSynthesis) {
        window.speechSynthesis.cancel()
      }
    }
  }, [])

  // Synthesize agent speech using TTS
  const speakAgentReply = (text: string, language = 'en-IN') => {
    if (!('speechSynthesis' in window)) return
    window.speechSynthesis.cancel()

    const utterance = new SpeechSynthesisUtterance(text)
    utterance.rate = 1.05
    utterance.pitch = 0.85

    // Sarvam audio is preferred by the response handler; this is the browser fallback.
    const preferredVoice = selectMaleSpeechVoice(window.speechSynthesis.getVoices(), language)

    if (preferredVoice) {
      utterance.voice = preferredVoice
    }
    utterance.lang = language

    utterance.onstart = () => setIsSpeaking(true)
    utterance.onend = () => {
      setIsSpeaking(false)
      if (handsFreeRef.current) {
        setTimeout(() => {
          startListeningRef.current()
        }, 350)
      }
    }
    utterance.onerror = () => setIsSpeaking(false)

    window.speechSynthesis.speak(utterance)
  }

  const handleProcessVoiceInput = async (audio: Blob) => {
    if (!audio.size || isProcessingRef.current) return
    isProcessingRef.current = true
    setIsProcessing(true)
    try {
      const response = await patientService.sendVoiceAssistantTurn(audio, sessionId)
      setTranscript(response.transcript)
      setMessages((prev) => [...prev, {
        id: `u_${Date.now()}`,
        sender: 'patient',
        text: response.transcript,
        timestamp: formatClockIST(),
      }])

      const botMsg: ChatMessage = {
        id: `a_${Date.now()}`,
        sender: 'assistant',
        text: response.reply,
        timestamp: formatClockIST(),
        targetSlot: response.target_slot,
        isConfirmed: response.booking_confirmed,
      }

      setMessages((prev) => [...prev, botMsg])
      if (response.audio_url) {
        const audio = new Audio(resolveVoiceAudioUrl(response.audio_url))
        audio.onplay = () => setIsSpeaking(true)
        audio.onended = () => {
          setIsSpeaking(false)
          if (handsFreeRef.current) {
            setTimeout(() => {
              startListeningRef.current()
            }, 350)
          }
        }
        audio.onerror = () => speakAgentReply(response.reply, response.language)
        await audio.play()
      } else {
        speakAgentReply(response.reply, response.language)
      }
    } catch {
      const fallbackMsg: ChatMessage = {
        id: `err_${Date.now()}`,
        sender: 'assistant',
        text: 'I apologize, I had trouble processing that request. Please try again or switch to the call tab.',
        timestamp: formatClockIST(),
      }
      setMessages((prev) => [...prev, fallbackMsg])
    } finally {
      isProcessingRef.current = false
      setIsProcessing(false)
    }
  }

  const stopListening = () => {
    if (vadAnimationRef.current) {
      cancelAnimationFrame(vadAnimationRef.current)
      vadAnimationRef.current = null
    }
    if (audioContextRef.current) {
      try {
        audioContextRef.current.close().catch(() => {})
      } catch {}
      audioContextRef.current = null
    }
    setUserIsSpeaking(false)
    hasDetectedSpeechRef.current = false
    if (mediaRecorderRef.current?.state === 'recording') {
      mediaRecorderRef.current.stop()
    }
  }

  const startListening = () => {
    if (isSpeaking || isProcessingRef.current) return

    navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
      const recorder = new MediaRecorder(stream)
      audioChunksRef.current = []
      mediaRecorderRef.current = recorder
      discardRecordingRef.current = false
      hasDetectedSpeechRef.current = false

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data)
      }
      recorder.onstop = () => {
        if (vadAnimationRef.current) {
          cancelAnimationFrame(vadAnimationRef.current)
          vadAnimationRef.current = null
        }
        if (audioContextRef.current) {
          try {
            audioContextRef.current.close().catch(() => {})
          } catch {}
          audioContextRef.current = null
        }
        setUserIsSpeaking(false)
        stream.getTracks().forEach((track) => track.stop())
        setIsListening(false)
        if (discardRecordingRef.current) {
          audioChunksRef.current = []
          return
        }
        const audio = new Blob(audioChunksRef.current, { type: recorder.mimeType || 'audio/webm' })
        audioChunksRef.current = []
        if (audio.size > 0) void handleProcessVoiceInput(audio)
      }
      recorder.start()
      setTranscript('')
      setSpeechError(null)
      setIsListening(true)

      // AudioContext VAD
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      if (AudioCtx) {
        try {
          const audioCtx = new AudioCtx()
          audioContextRef.current = audioCtx
          const sourceNode = audioCtx.createMediaStreamSource(stream)
          const analyser = audioCtx.createAnalyser()
          analyser.fftSize = 512
          analyser.smoothingTimeConstant = 0.2
          sourceNode.connect(analyser)

          const dataArray = new Uint8Array(analyser.frequencyBinCount)
          let silenceStartTime: number | null = null
          const sessionStartTime = Date.now()

          const monitorLevels = () => {
            if (recorder.state !== 'recording') return
            analyser.getByteFrequencyData(dataArray)
            let sum = 0
            for (let i = 0; i < dataArray.length; i++) sum += dataArray[i]
            const average = sum / dataArray.length

            if (average > 14) {
              hasDetectedSpeechRef.current = true
              setUserIsSpeaking(true)
              silenceStartTime = null
            } else {
              setUserIsSpeaking(false)
              if (hasDetectedSpeechRef.current && handsFreeRef.current) {
                if (silenceStartTime === null) {
                  silenceStartTime = Date.now()
                } else if (Date.now() - silenceStartTime > 1600) {
                  silenceStartTime = null
                  if (recorder.state === 'recording') {
                    recorder.stop()
                    return
                  }
                }
              } else if (!hasDetectedSpeechRef.current && handsFreeRef.current && Date.now() - sessionStartTime > 12000) {
                if (recorder.state === 'recording') {
                  discardRecordingRef.current = true
                  recorder.stop()
                  return
                }
              }
            }

            vadAnimationRef.current = requestAnimationFrame(monitorLevels)
          }

          vadAnimationRef.current = requestAnimationFrame(monitorLevels)
        } catch (e) {
          console.warn('VAD AudioContext init failed:', e)
        }
      }
    }).catch(() => {
      setSpeechError('Microphone permission was denied. Please allow microphone access.')
      setIsListening(false)
    })
  }
  startListeningRef.current = startListening

  const toggleListening = () => {
    if (isListening) {
      stopListening()
    } else {
      startListening()
    }
  }

  const resetVoiceChat = () => {
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel()
    }
    setIsSpeaking(false)
    setIsListening(false)
    setTranscript('')
    setSessionId(`voice_${Date.now()}`)
    setMessages([
      {
        id: 'welcome_reset',
        sender: 'assistant',
        text: `Hello! Welcome to ${ENV.CLINIC_NAME}. How can I help you today?`,
        timestamp: formatClockIST(),
      },
    ])
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Intro Header */}
      <div className="text-center space-y-2">
        <Badge variant="teal" className="mb-1">
          <Sparkles className="w-3 h-3 text-[#0D9488] mr-1 inline" /> Real-time Speech AI
        </Badge>
        <h2 className="text-2xl sm:text-3xl font-semibold text-[#0F172A] tracking-tight">
          Clinical Voice Assistant
        </h2>
        <p className="text-sm text-[#475569] max-w-xl mx-auto">
          Talk directly with our scheduling AI using your computer or mobile microphone. Real-time slot lookup and voice replies.
        </p>
      </div>

      {/* Main Interactive Assistant Container */}
      <Card glow="teal" className="space-y-6">
        {/* Dynamic Waveform Visualizer */}
        <div className="space-y-3">
          <div className="flex items-center justify-between px-2">
            <span className="text-xs font-semibold text-[#475569] uppercase tracking-wider">
              Audio Frequency & Feedback
            </span>
            <div className="flex items-center gap-2">
              {isListening && (
                <span className="inline-flex items-center gap-1.5 text-xs text-[#E11D48] animate-pulse font-medium">
                  <span className={`w-2 h-2 rounded-full ${userIsSpeaking ? 'bg-[#059669]' : 'bg-[#E11D48]'}`} />
                  {userIsSpeaking ? 'Hearing your voice...' : 'Listening to you...'}
                </span>
              )}
              {isSpeaking && (
                <span className="inline-flex items-center gap-1.5 text-xs text-[#0D9488] animate-pulse font-medium">
                  <Volume2 className="w-3.5 h-3.5" /> AI Speaking...
                </span>
              )}
              {!isListening && !isSpeaking && (
                <span className="text-xs text-[#64748B]">Standby (Mic Ready)</span>
              )}
            </div>
          </div>

          <AudioWaveVisualizer
            isActive={isListening || isSpeaking || isProcessing}
            isSpeaking={isSpeaking}
            barCount={24}
          />
        </div>

        {/* Live Conversation Transcript */}
        <div className="max-h-[320px] min-h-[180px] overflow-y-auto space-y-3 p-4 rounded-xl bg-[#F8FAFC] border border-[#E2E8F0]">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex items-start gap-3 ${
                msg.sender === 'patient' ? 'justify-end' : 'justify-start'
              }`}
            >
              {msg.sender === 'assistant' && (
                <div className="w-8 h-8 rounded-lg bg-[#CCFBF1] text-[#0D9488] flex items-center justify-center shrink-0 border border-[#99F6E4]">
                  <Bot className="w-4 h-4" />
                </div>
              )}

              <div
                className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                  msg.sender === 'patient'
                    ? 'bg-[#0F766E] text-white rounded-tr-none shadow-sm'
                    : 'bg-white border border-[#E2E8F0] text-[#0F172A] rounded-tl-none shadow-[var(--shadow-card)]'
                }`}
              >
                <div className="flex items-center justify-between gap-4 mb-1 text-[11px] opacity-70">
                  <span className="font-semibold">
                    {msg.sender === 'patient' ? 'You' : 'Clinical AI'}
                  </span>
                  <span>{msg.timestamp}</span>
                </div>
                <p className="whitespace-pre-wrap">{msg.text}</p>

                {/* Target slot confirmation pill */}
                {msg.targetSlot && (
                  <div className="mt-2.5 p-2.5 rounded-lg bg-[#F0FDFA] border border-[#99F6E4] text-xs text-[#0F766E]">
                    <p className="font-semibold text-[#0F766E]">Appointment Option</p>
                    <p>Doctor: {msg.targetSlot.doctor_name || 'Assigned Specialist'}</p>
                    <p>Time: {msg.targetSlot.time || 'Next Open Slot'}</p>
                  </div>
                )}
              </div>

              {msg.sender === 'patient' && (
                <div className="w-8 h-8 rounded-lg bg-[#CCFBF1] text-[#0F766E] flex items-center justify-center shrink-0 border border-[#99F6E4]">
                  <User className="w-4 h-4" />
                </div>
              )}
            </div>
          ))}

          {/* Active transcription preview while user is speaking */}
          {transcript && (
            <div className="flex items-start justify-end gap-3 opacity-90 animate-pulse">
              <div className="max-w-[80%] rounded-2xl px-4 py-2.5 bg-white border border-[#14B8A6] text-[#0D9488] text-sm italic shadow-sm">
                "{transcript}"
              </div>
            </div>
          )}

          {/* Agent processing spinner */}
          {isProcessing && (
            <div className="flex items-center gap-2 text-xs text-[#0D9488] pl-2">
              <span className="w-2 h-2 rounded-full bg-[#14B8A6] animate-ping" />
              Thinking & consulting clinic scheduler...
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Voice Controls Bar */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-2 border-t border-[#E2E8F0]">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={resetVoiceChat}
            leftIcon={<RotateCcw className="w-3.5 h-3.5" />}
          >
            Reset Voice Session
          </Button>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => {
                const next = !handsFreeMode
                setHandsFreeMode(next)
                handsFreeRef.current = next
              }}
              className={`px-3 py-1.5 rounded-full text-xs font-semibold border transition-all flex items-center gap-1.5 cursor-pointer ${
                handsFreeMode
                  ? 'bg-[#CCFBF1] border-[#99F6E4] text-[#0D9488] shadow-sm'
                  : 'bg-white border-[#CBD5E1] text-[#64748B] hover:text-[#0F172A]'
              }`}
              title="When Hands-Free is active, the assistant automatically listens after speaking and submits after a brief pause."
            >
              <span className={`w-2 h-2 rounded-full ${handsFreeMode ? 'bg-[#0D9488] animate-pulse' : 'bg-slate-400'}`} />
              Hands-Free: {handsFreeMode ? 'ON' : 'OFF'}
            </button>

            <Button
              type="button"
              variant={isListening ? 'danger' : 'primary'}
              size="lg"
              onClick={toggleListening}
              className={isListening ? 'animate-pulse' : ''}
              leftIcon={
                isListening ? (
                  <MicOff className="w-5 h-5 text-white" />
                ) : (
                  <Mic className="w-5 h-5 text-white" />
                )
              }
            >
              {isListening ? (userIsSpeaking ? 'Hearing you...' : 'Stop & Send') : 'Click to Speak'}
            </Button>
          </div>
        </div>

        {/* Error notification if mic blocked */}
        {speechError && (
          <div className="p-3.5 rounded-xl bg-[#FFE4E6] border border-[#FECDD3] text-[#E11D48] text-xs flex items-center gap-2.5">
            <AlertCircle className="w-4 h-4 text-[#E11D48] shrink-0" />
            <span>{speechError}</span>
          </div>
        )}
      </Card>
    </div>
  )
}
