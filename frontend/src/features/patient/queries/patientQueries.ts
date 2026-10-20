import { useMutation } from '@tanstack/react-query'
import { patientService } from '../services/patientService'
import type {
  ChatApiRequest,
  ChatApiResponse,
  TriggerCallRequest,
  TriggerCallResponse,
} from '../../../types'

export const useTriggerCall = () => {
  return useMutation<TriggerCallResponse, Error, TriggerCallRequest>({
    mutationFn: (data) => patientService.triggerCall(data),
  })
}

export const useSendChatMessage = () => {
  return useMutation<ChatApiResponse, Error, ChatApiRequest>({
    mutationFn: (data) => patientService.sendChatMessage(data),
  })
}
