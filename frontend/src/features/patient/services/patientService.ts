import { apiClient } from '../../../lib/axios'
import type {
  ChatApiRequest,
  ChatApiResponse,
  TriggerCallRequest,
  TriggerCallResponse,
  VoiceAssistantSessionResponse,
  VoiceAssistantTurnResponse,
} from '../../../types'

export const patientService = {
  /**
   * Triggers Twilio outbound scheduling call to the patient's phone.
   */
  async triggerCall(data: TriggerCallRequest): Promise<TriggerCallResponse> {
    const response = await apiClient.post<TriggerCallResponse>('/api/calls/trigger', {
      to_phone: data.to_phone,
    })
    return response.data
  },

  /**
   * Sends a message to the clinic AI assistant (LangGraph) and returns reply.
   */
  async sendChatMessage(payload: ChatApiRequest): Promise<ChatApiResponse> {
    const response = await apiClient.post<ChatApiResponse>('/api/chat', payload)
    return response.data
  },

  async createVoiceAssistantSession(): Promise<VoiceAssistantSessionResponse> {
    const response = await apiClient.post<VoiceAssistantSessionResponse>('/api/voice-assistant/session')
    return response.data
  },

  async sendVoiceAssistantTurn(
    audio: Blob,
    sessionId: string,
  ): Promise<VoiceAssistantTurnResponse> {
    const formData = new FormData()
    formData.append('audio', audio, 'voice.webm')
    formData.append('session_id', sessionId)
    const response = await apiClient.post<VoiceAssistantTurnResponse>(
      '/api/voice-assistant/turn',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    )
    return response.data
  },

  async generateTTS(text: string, language: string = 'en-IN'): Promise<{ audio_url: string }> {
    const response = await apiClient.post<{ audio_url: string }>('/api/voice-assistant/tts', {
      text,
      language,
    })
    return response.data
  },
}
