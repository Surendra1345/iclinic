import React, { useState, useEffect, useRef } from 'react'
import { Mic, MicOff, Volume2, Sparkles, AlertCircle, RotateCcw, Bot, User } from 'lucide-react'
import { Card } from '../../../components/ui/Card'
import { Button } from '../../../components/ui/Button'
import { Badge } from '../../../components/ui/Badge'
import { AudioWaveVisualizer } from '../../../components/common/AudioWaveVisualizer'
import { patientService } from '../services/patientService'
import { ENV } from '../../../config/env'
import type { ChatMessage } from '../../../types'

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
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
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
    utterance.pitch = 1.0

    // Sarvam audio is preferred by the response handler; this is the browser fallback.
    const voices = window.speechSynthesis.getVoices()
    const preferredVoice =
      voices.find((v) => v.lang.toLowerCase() === language.toLowerCase()) ||
      voices.find((v) => v.lang.toLowerCase().startsWith(language.slice(0, 2).toLowerCase())) ||
      voices.find((v) => v.name.includes('Google') || v.name.includes('Natural')) ||
      voices[0]

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
    setIsProcessing(true)
    try {
      const response = await patientService.sendVoiceAssistantTurn(audio, sessionId)
      setTranscript(response.transcript)
      setMessages((prev) => [...prev, {
        id: `u_${Date.now()}`,
        sender: 'patient',
        text: response.transcript,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }])

      const botMsg: ChatMessage = {
        id: `a_${Date.now()}`,
        sender: 'assistant',
        text: response.reply,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        targetSlot: response.target_slot,
        isConfirmed: response.booking_confirmed,
      }

      setMessages((prev) => [...prev, botMsg])
      if (response.audio_url) {
        const audio = new Audio(`${ENV.API_BASE_URL}${response.audio_url}`)
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
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }
      setMessages((prev) => [...prev, fallbackMsg])
    } finally {
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
    if (isSpeaking || isProcessing) return

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
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      },
    ])
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Intro Header */}
      <div className="text-center space-y-2">
        <Badge variant="teal" className="mb-1">
          <Sparkles className="w-3 h-3 text-teal-400 mr-1 inline" /> Real-time Speech AI
        </Badge>
        <h2 className="text-2xl sm:text-3xl font-semibold text-white tracking-tight">
          Clinical Voice Assistant
        </h2>
        <p className="text-sm text-slate-400 max-w-xl mx-auto">
          Talk directly with our scheduling AI using your computer or mobile microphone. Real-time slot lookup and voice replies.
        </p>
      </div>

      {/* Main Interactive Assistant Container */}
      <Card glow="teal" className="space-y-6">
        {/* Dynamic Waveform Visualizer */}
        <div className="space-y-3">
          <div className="flex items-center justify-between px-2">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Audio Frequency & Feedback
            </span>
            <div className="flex items-center gap-2">
              {isListening && (
                <span className="inline-flex items-center gap-1.5 text-xs text-rose-400 animate-pulse font-medium">
                  <span className={`w-2 h-2 rounded-full ${userIsSpeaking ? 'bg-emerald-400' : 'bg-rose-500'}`} />
                  {userIsSpeaking ? 'Hearing your voice...' : 'Listening to you...'}
                </span>
              )}
              {isSpeaking && (
                <span className="inline-flex items-center gap-1.5 text-xs text-teal-400 animate-pulse font-medium">
                  <Volume2 className="w-3.5 h-3.5" /> AI Speaking...
                </span>
              )}
              {!isListening && !isSpeaking && (
                <span className="text-xs text-slate-500">Standby (Mic Ready)</span>
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
        <div className="max-h-[320px] min-h-[180px] overflow-y-auto space-y-3 p-4 rounded-xl bg-slate-950/70 border border-slate-800/80">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex items-start gap-3 ${
                msg.sender === 'patient' ? 'justify-end' : 'justify-start'
              }`}
            >
              {msg.sender === 'assistant' && (
                <div className="w-8 h-8 rounded-lg bg-teal-500/20 text-teal-300 flex items-center justify-center shrink-0 border border-teal-500/30">
                  <Bot className="w-4 h-4" />
                </div>
              )}

              <div
                className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                  msg.sender === 'patient'
                    ? 'bg-gradient-to-r from-teal-600 to-emerald-600 text-white rounded-tr-none shadow-md'
                    : 'bg-slate-900 border border-slate-800 text-slate-200 rounded-tl-none shadow-inner'
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
                  <div className="mt-2.5 p-2.5 rounded-lg bg-teal-950/80 border border-teal-500/30 text-xs text-teal-200">
                    <p className="font-semibold text-teal-300">Appointment Option</p>
                    <p>Doctor: {msg.targetSlot.doctor_name || 'Assigned Specialist'}</p>
                    <p>Time: {msg.targetSlot.time || 'Next Open Slot'}</p>
                  </div>
                )}
              </div>

              {msg.sender === 'patient' && (
                <div className="w-8 h-8 rounded-lg bg-emerald-500/20 text-emerald-300 flex items-center justify-center shrink-0 border border-emerald-500/30">
                  <User className="w-4 h-4" />
                </div>
              )}
            </div>
          ))}

          {/* Active transcription preview while user is speaking */}
          {transcript && (
            <div className="flex items-start justify-end gap-3 opacity-90 animate-pulse">
              <div className="max-w-[80%] rounded-2xl px-4 py-2.5 bg-slate-800/80 border border-teal-500/40 text-teal-200 text-sm italic">
                "{transcript}"
              </div>
            </div>
          )}

          {/* Agent processing spinner */}
          {isProcessing && (
            <div className="flex items-center gap-2 text-xs text-teal-400 pl-2">
              <span className="w-2 h-2 rounded-full bg-teal-400 animate-ping" />
              Thinking & consulting clinic scheduler...
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Voice Controls Bar */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-2 border-t border-slate-800">
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
              className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-all flex items-center gap-1.5 cursor-pointer ${
                handsFreeMode
                  ? 'bg-teal-500/20 border-teal-500/50 text-teal-300 shadow-sm shadow-teal-500/20'
                  : 'bg-slate-900 border-slate-700 text-slate-400 hover:text-slate-200'
              }`}
              title="When Hands-Free is active, the assistant automatically listens after speaking and submits after a brief pause."
            >
              <span className={`w-2 h-2 rounded-full ${handsFreeMode ? 'bg-teal-400 animate-pulse' : 'bg-slate-500'}`} />
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
                  <MicOff className="w-5 h-5 text-rose-300" />
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
          <div className="p-3.5 rounded-xl bg-rose-950/60 border border-rose-500/40 text-rose-200 text-xs flex items-center gap-2.5">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{speechError}</span>
          </div>
        )}
      </Card>
    </div>
  )
}
