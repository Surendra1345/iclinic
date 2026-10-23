import React, { useState, useEffect, useRef, useCallback } from 'react'
import { Mic, MicOff, X, Volume2, Sparkles, AlertCircle } from 'lucide-react'
import { Button } from '../../../components/ui/Button'
import { patientService } from '../services/patientService'
import { resolveVoiceAudioUrl, selectMaleSpeechVoice } from './selectMaleSpeechVoice'
import type { ChatMessage } from '../../../types'

interface VoiceOverlayProps {
  isOpen: boolean
  onClose: () => void
  onNewMessage: (msg: ChatMessage) => void
  sessionId: string
}

export const VoiceOverlay: React.FC<VoiceOverlayProps> = ({
  isOpen,
  onClose,
  onNewMessage,
  sessionId,
}) => {
  const [isListening, setIsListening] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [lastAgentSpeech, setLastAgentSpeech] = useState<string>(
    'Hello! Welcome to City Care Clinic. How can I assist you today?'
  )
  const [speechError, setSpeechError] = useState<string | null>(null)
  const [handsFreeMode, setHandsFreeMode] = useState<boolean>(true)
  const [userIsSpeaking, setUserIsSpeaking] = useState<boolean>(false)

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  const discardRecordingRef = useRef(false)
  const recordingStreamRef = useRef<MediaStream | null>(null)
  const currentAudioRef = useRef<HTMLAudioElement | null>(null)
  const activeUtteranceRef = useRef<SpeechSynthesisUtterance | null>(null)
  const isProcessingRef = useRef<boolean>(false)
  const submitVoiceInputRef = useRef<(audio: Blob) => Promise<void>>(async () => {})
  const isSpeakingRef = useRef<boolean>(false)
  const isOpenRef = useRef<boolean>(isOpen)
  const hasSpokenGreetingRef = useRef<boolean>(false)
  const handsFreeRef = useRef<boolean>(true)
  const audioContextRef = useRef<AudioContext | null>(null)
  const vadAnimationRef = useRef<number | null>(null)
  const hasDetectedSpeechRef = useRef<boolean>(false)
  const startListeningRef = useRef<() => Promise<void>>(async () => {})

  isOpenRef.current = isOpen
  isSpeakingRef.current = isSpeaking
  handsFreeRef.current = handsFreeMode

  // Stop all active audio and speech
  const stopAllAudio = useCallback(() => {
    if (currentAudioRef.current) {
      try {
        currentAudioRef.current.pause()
        currentAudioRef.current.src = ''
      } catch {}
      currentAudioRef.current = null
    }
    if (window.speechSynthesis) {
      try {
        window.speechSynthesis.cancel()
      } catch {}
    }
    activeUtteranceRef.current = null
    setIsSpeaking(false)
    isSpeakingRef.current = false
  }, [])

  // Start recording audio so Sarvam can recognize English, Tamil, or Telugu.
  const startListening = useCallback(async () => {
    if (!isOpenRef.current || isSpeakingRef.current || isProcessingRef.current) return
    let stream: MediaStream | null = null
    try {
      const activeStream = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream = activeStream
      if (!isOpenRef.current || isProcessingRef.current) {
        activeStream.getTracks().forEach((track) => track.stop())
        return
      }
      const recorder = new MediaRecorder(activeStream)
      recordingStreamRef.current = activeStream
      mediaRecorderRef.current = recorder
      audioChunksRef.current = []
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
        activeStream.getTracks().forEach((track) => track.stop())
        recordingStreamRef.current = null
        mediaRecorderRef.current = null
        setIsListening(false)
        if (discardRecordingRef.current) {
          audioChunksRef.current = []
          return
        }
        const audio = new Blob(audioChunksRef.current, { type: recorder.mimeType || 'audio/webm' })
        audioChunksRef.current = []
        if (audio.size > 0) void submitVoiceInputRef.current(audio)
      }
      recorder.start()
      setIsListening(true)
      setSpeechError(null)

      // Setup Web Audio API Analyser for Voice Activity Detection (VAD)
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      if (AudioCtx) {
        try {
          const audioCtx = new AudioCtx()
          audioContextRef.current = audioCtx
          const sourceNode = audioCtx.createMediaStreamSource(activeStream)
          const analyser = audioCtx.createAnalyser()
          analyser.fftSize = 512
          analyser.smoothingTimeConstant = 0.2
          sourceNode.connect(analyser)

          const dataArray = new Uint8Array(analyser.frequencyBinCount)
          let silenceStartTime: number | null = null
          const sessionStartTime = Date.now()

          const monitorAudioLevels = () => {
            if (!recordingStreamRef.current || mediaRecorderRef.current?.state !== 'recording') return
            analyser.getByteFrequencyData(dataArray)
            let sum = 0
            for (let i = 0; i < dataArray.length; i++) {
              sum += dataArray[i]
            }
            const average = sum / dataArray.length

            // Volume threshold for human voice
            const SPEECH_THRESHOLD = 14
            const isAudible = average > SPEECH_THRESHOLD

            if (isAudible) {
              hasDetectedSpeechRef.current = true
              setUserIsSpeaking(true)
              silenceStartTime = null
            } else {
              setUserIsSpeaking(false)
              if (hasDetectedSpeechRef.current && handsFreeRef.current) {
                // Patient spoke and is now quiet -> track silence
                if (silenceStartTime === null) {
                  silenceStartTime = Date.now()
                } else if (Date.now() - silenceStartTime > 1600) {
                  // 1.6s of silence after speech -> auto-stop and send!
                  silenceStartTime = null
                  if (mediaRecorderRef.current?.state === 'recording') {
                    mediaRecorderRef.current.stop()
                    return
                  }
                }
              } else if (!hasDetectedSpeechRef.current && handsFreeRef.current && Date.now() - sessionStartTime > 12000) {
                // 12s of complete silence without speaking -> pause to save battery
                if (mediaRecorderRef.current?.state === 'recording') {
                  discardRecordingRef.current = true
                  mediaRecorderRef.current.stop()
                  return
                }
              }
            }

            vadAnimationRef.current = requestAnimationFrame(monitorAudioLevels)
          }

          vadAnimationRef.current = requestAnimationFrame(monitorAudioLevels)
        } catch (e) {
          console.warn('VAD AudioContext init failed:', e)
        }
      }
    } catch {
      stream?.getTracks().forEach((track) => track.stop())
      setIsListening(false)
      setSpeechError('Microphone access failed. Please allow microphone access and try again.')
    }
  }, [])
  startListeningRef.current = startListening

  // Stop recording and submit the captured audio.
  const stopListening = useCallback(() => {
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
      try {
        mediaRecorderRef.current.stop()
      } catch {}
    } else {
      recordingStreamRef.current?.getTracks().forEach((track) => track.stop())
      recordingStreamRef.current = null
    }
  }, [])

  // Browser speech synthesis fallback
  const speakBrowserFallback = useCallback((text: string, language = 'en-IN') => {
    if (!('speechSynthesis' in window)) {
      return
    }

    try {
      window.speechSynthesis.cancel()
      window.speechSynthesis.resume()

      const utterance = new SpeechSynthesisUtterance(text)
      utterance.rate = 1.05
      utterance.pitch = 0.85
      activeUtteranceRef.current = utterance

      const preferredVoice = selectMaleSpeechVoice(window.speechSynthesis.getVoices(), language)

      if (preferredVoice) {
        utterance.voice = preferredVoice
      }

      utterance.onstart = () => {
        setIsSpeaking(true)
        isSpeakingRef.current = true
        setIsListening(false)
      }

      utterance.onend = () => {
        setIsSpeaking(false)
        isSpeakingRef.current = false
        activeUtteranceRef.current = null
        // Auto-listen after speech ends if hands-free is enabled
        if (handsFreeRef.current && isOpenRef.current && !isProcessingRef.current) {
          setTimeout(() => {
            if (isOpenRef.current && !isSpeakingRef.current && !isProcessingRef.current) {
              void startListeningRef.current()
            }
          }, 350)
        }
      }

      utterance.onerror = () => {
        setIsSpeaking(false)
        isSpeakingRef.current = false
        activeUtteranceRef.current = null
      }

      window.speechSynthesis.speak(utterance)
    } catch {
      setIsSpeaking(false)
      isSpeakingRef.current = false
    }
  }, [])

  // Play agent audio (Sarvam Bulbul studio voice with browser fallback)
  const playAgentVoice = useCallback((text: string, audioUrl?: string | null, language = 'en-IN') => {
    stopAllAudio()
    stopListening()

    if (audioUrl) {
      try {
        const audio = new Audio(resolveVoiceAudioUrl(audioUrl))
        currentAudioRef.current = audio

        audio.onplay = () => {
          setIsSpeaking(true)
          isSpeakingRef.current = true
          setIsListening(false)
        }

        audio.onended = () => {
          setIsSpeaking(false)
          isSpeakingRef.current = false
          currentAudioRef.current = null
          // Auto-listen after studio audio finishes playing
          if (handsFreeRef.current && isOpenRef.current && !isProcessingRef.current) {
            setTimeout(() => {
              if (isOpenRef.current && !isSpeakingRef.current && !isProcessingRef.current) {
                void startListeningRef.current()
              }
            }, 350)
          }
        }

        audio.onerror = () => {
          currentAudioRef.current = null
          speakBrowserFallback(text, language)
        }

        const playPromise = audio.play()
        if (playPromise !== undefined) {
          playPromise.catch(() => {
            currentAudioRef.current = null
            speakBrowserFallback(text, language)
          })
        }
      } catch {
        speakBrowserFallback(text, language)
      }
    } else {
      speakBrowserFallback(text, language)
    }
  }, [speakBrowserFallback, stopAllAudio, stopListening])

  // Submit recognized user speech to backend AI
  const submitVoiceInput = useCallback(async (audio: Blob) => {
    if (!audio.size || isProcessingRef.current) return

    isProcessingRef.current = true
    setIsProcessing(true)
    setTranscript('')

    try {
      const response = await patientService.sendVoiceAssistantTurn(audio, sessionId)
      setTranscript(response.transcript)
      onNewMessage({
        id: `u_${Date.now()}`,
        sender: 'patient',
        text: response.transcript,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      })

      const botMsg: ChatMessage = {
        id: `a_${Date.now()}`,
        sender: 'assistant',
        text: response.reply,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        targetSlot: response.target_slot,
        isConfirmed: response.booking_confirmed,
      }
      onNewMessage(botMsg)
      setLastAgentSpeech(response.reply)
      playAgentVoice(response.reply, response.audio_url, response.language)
    } catch (error) {
      const responseDetail = (error as {
        response?: { data?: { detail?: string } }
      })?.response?.data?.detail
      const fallback = 'I could not complete that voice request. Please try speaking again.'
      setSpeechError(responseDetail || 'The voice service could not complete this turn. Your saved transcript, if received, remains in the conversation history.')
      setLastAgentSpeech(fallback)
      playAgentVoice(fallback)
    } finally {
      isProcessingRef.current = false
      setIsProcessing(false)
    }
  }, [onNewMessage, playAgentVoice, sessionId])
  submitVoiceInputRef.current = submitVoiceInput

  // Prepare the voice session and play the initial greeting.
  useEffect(() => {
    if (!isOpen) {
      stopAllAudio()
      discardRecordingRef.current = true
      stopListening()
      setIsListening(false)
      setIsProcessing(false)
      hasSpokenGreetingRef.current = false
      return
    }

    // Pre-unlock HTML5 Audio on user click
    try {
      const unlockAudio = new Audio()
      unlockAudio.play().catch(() => {})
    } catch {}

    // Play welcome greeting with voice on open
    if (!hasSpokenGreetingRef.current) {
      hasSpokenGreetingRef.current = true
      const greeting = 'Hello! Welcome to City Care Clinic. How can I assist you today?'
      patientService.generateTTS(greeting)
        .then((res) => {
          if (isOpenRef.current) {
            playAgentVoice(greeting, res.audio_url)
          }
        })
        .catch(() => {
          if (isOpenRef.current) {
            playAgentVoice(greeting)
          }
        })
    }

    return () => {
      stopAllAudio()
      discardRecordingRef.current = true
      stopListening()
    }
  }, [isOpen, playAgentVoice, stopAllAudio, stopListening])

  // Mic Button Toggle
  const toggleMic = () => {
    // If assistant is speaking, interrupt it and listen to the patient
    if (isSpeaking) {
      stopAllAudio()
    }

    // Tap again to submit the captured audio.
    if (isListening) {
      stopListening()
    } else {
      setSpeechError(null)
      setTranscript('')
      void startListening()
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-between p-6 bg-[#F6F9FB]/95 backdrop-blur-2xl animate-fadeIn text-[#0F172A]">
      {/* Top Header */}
      <div className="w-full max-w-xl flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs text-[#0D9488] font-bold tracking-wide uppercase">
          <Sparkles className="w-4 h-4 animate-spin" />
          <span>City Care Live Voice</span>
        </div>
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
            title="Toggle Hands-Free Auto-Listen Mode"
          >
            <Sparkles className={`w-3.5 h-3.5 ${handsFreeMode ? 'text-[#0D9488] animate-pulse' : 'text-[#64748B]'}`} />
            <span>Hands-Free: {handsFreeMode ? 'ON' : 'OFF'}</span>
          </button>

          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-full text-[#64748B] hover:text-[#0F172A] bg-white border border-[#E2E8F0] shadow-sm transition-colors cursor-pointer"
            title="Close Voice Assistant"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* Central Pulsating Voice Sphere */}
      <div className="flex flex-col items-center justify-center space-y-8 my-auto max-w-lg text-center">
        <div className="relative flex items-center justify-center">
          {/* Animated Glow Rings */}
          <div
            className={`absolute w-56 h-56 rounded-full transition-all duration-700 blur-2xl ${
              isSpeaking
                ? 'bg-teal-500/30 scale-125 animate-pulse'
                : isListening
                ? 'bg-emerald-500/30 scale-110 animate-pulse'
                : isProcessing
                ? 'bg-cyan-500/20 scale-100 animate-spin'
                : 'bg-teal-500/10 scale-90'
            }`}
          />

          {/* Central Interactive Orb */}
          <button
            type="button"
            onClick={toggleMic}
            className={`relative w-36 h-36 rounded-full flex items-center justify-center transition-all duration-500 shadow-2xl border cursor-pointer outline-none ${
              isSpeaking
                ? 'bg-gradient-to-tr from-[#14B8A6] via-[#06B6D4] to-[#10B981] border-teal-300 scale-105 shadow-teal-500/40'
                : isListening
                ? 'bg-gradient-to-tr from-[#10B981] via-[#14B8A6] to-[#06B6D4] border-emerald-300 scale-100 shadow-emerald-500/40'
                : isProcessing
                ? 'bg-gradient-to-tr from-[#0284C7] to-[#0F766E] border-cyan-400 animate-pulse shadow-cyan-500/30'
                : 'bg-white border-[#CBD5E1] hover:border-[#14B8A6] shadow-md'
            }`}
          >
            {isSpeaking ? (
              <Volume2 className="w-12 h-12 text-white animate-bounce" />
            ) : isListening ? (
              <Mic className="w-12 h-12 text-white animate-pulse" />
            ) : isProcessing ? (
              <Sparkles className="w-10 h-10 text-white animate-spin" />
            ) : (
              <Sparkles className="w-10 h-10 text-[#14B8A6]" />
            )}
          </button>
        </div>

        {/* Live Transcription & Status */}
        <div className="space-y-3 px-4">
          <p className="text-xs uppercase tracking-widest font-semibold text-[#64748B]">
            {isSpeaking
              ? 'AI speaking · tap orb to interrupt'
              : isProcessing
              ? 'Consulting Clinic Schedule...'
              : userIsSpeaking
              ? 'Hearing you speak...'
              : isListening
              ? handsFreeMode
                ? 'Listening... speak anytime (auto-sends on pause)'
                : 'Recording... tap mic when you finish'
              : 'Tap Microphone to Speak'}
          </p>

          {/* Spoken transcript or AI reply */}
          <div className="min-h-[60px] flex items-center justify-center">
            {transcript ? (
              <p className="text-lg font-medium text-[#0D9488] italic animate-pulse">
                "{transcript}"
              </p>
            ) : (
              <p className="text-sm sm:text-base text-[#0F172A] max-w-md leading-relaxed font-medium">
                {lastAgentSpeech}
              </p>
            )}
          </div>
        </div>

        {speechError && (
          <div className="p-3 rounded-xl bg-[#FFE4E6] border border-[#FECDD3] text-[#E11D48] text-xs flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-[#E11D48] shrink-0" />
            <span>{speechError}</span>
          </div>
        )}
      </div>

      {/* Bottom Controls Bar */}
      <div className="w-full max-w-sm flex items-center justify-center gap-6 pb-4">
        <Button
          type="button"
          variant={isListening ? 'danger' : isSpeaking ? 'secondary' : 'primary'}
          size="lg"
          onClick={toggleMic}
          title={isSpeaking ? 'Interrupt assistant and speak' : 'Speak or interrupt assistant'}
          className="rounded-full w-16 h-16 p-0 shadow-xl cursor-pointer"
          leftIcon={
            isListening ? (
              <MicOff className="w-6 h-6 text-[#E11D48]" />
            ) : isSpeaking ? (
              <Volume2 className="w-6 h-6 text-[#0F172A]" />
            ) : (
              <Mic className="w-6 h-6 text-white" />
            )
          }
        />
        <Button
          type="button"
          variant="outline"
          size="md"
          onClick={onClose}
          className="rounded-xl px-5 text-xs text-[#475569] cursor-pointer"
        >
          Exit to Chat
        </Button>
      </div>
    </div>
  )
}
