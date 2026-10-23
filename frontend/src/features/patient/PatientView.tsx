import React, { useState } from 'react'
import { PhoneCall, Mic, MessageSquare } from 'lucide-react'
import { CallTab } from './components/CallTab'
import { VoiceAssistantTab } from './components/VoiceAssistantTab'
import { ChatTab } from './components/ChatTab'

export type PatientSubTab = 'call' | 'voice' | 'chat'

export const PatientView: React.FC = () => {
  const [activeTab, setActiveTab] = useState<PatientSubTab>('call')

  const tabs = [
    {
      id: 'call' as const,
      label: 'Call Me Tab',
      icon: <PhoneCall className="w-4 h-4" />,
      badge: 'Twilio Outbound',
      description: 'Enter number & receive phone call',
    },
    {
      id: 'voice' as const,
      label: 'Voice Assistant Tab',
      icon: <Mic className="w-4 h-4" />,
      badge: 'Browser Audio',
      description: 'Speak directly into microphone',
    },
    {
      id: 'chat' as const,
      label: 'Clinic Chat Tab',
      icon: <MessageSquare className="w-4 h-4" />,
      badge: 'Interactive AI',
      description: 'Type symptoms & book slots',
    },
  ]

  return (
    <div className="space-y-8 animate-fadeIn">
      {/* Subtab Selector Navigation */}
      <div className="flex justify-center">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 p-1.5 rounded-2xl bg-[#F1F5F9] border border-[#E2E8F0] shadow-sm max-w-2xl w-full">
          {tabs.map((tab) => {
            const isActive = activeTab === tab.id
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`flex flex-col items-center justify-center p-3 rounded-xl transition-all duration-200 cursor-pointer ${
                  isActive
                    ? 'bg-[#F0FDFA] border border-[#14B8A6]/50 text-[#0F766E] shadow-sm'
                    : 'text-[#475569] hover:text-[#0F172A] hover:bg-white/60 border border-transparent'
                }`}
              >
                <div className="flex items-center gap-2 font-semibold text-xs sm:text-sm">
                  <span className={isActive ? 'text-[#0D9488]' : 'text-[#64748B]'}>
                    {tab.icon}
                  </span>
                  <span>{tab.label}</span>
                </div>
                <span className="text-[10px] text-[#64748B] mt-0.5 hidden sm:block">
                  {tab.description}
                </span>
              </button>
            )
          })}
        </div>
      </div>

      {/* Render Active Patient Subtab */}
      <div className="transition-all duration-300">
        {activeTab === 'call' && <CallTab />}
        {activeTab === 'voice' && <VoiceAssistantTab />}
        {activeTab === 'chat' && <ChatTab />}
      </div>
    </div>
  )
}
