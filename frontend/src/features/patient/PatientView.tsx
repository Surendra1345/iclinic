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
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 p-1.5 rounded-2xl bg-slate-900/90 border border-slate-800 shadow-xl max-w-2xl w-full">
          {tabs.map((tab) => {
            const isActive = activeTab === tab.id
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`flex flex-col items-center justify-center p-3 rounded-xl transition-all duration-200 cursor-pointer ${
                  isActive
                    ? 'bg-gradient-to-r from-teal-500/20 to-emerald-500/20 border border-teal-500/40 text-white shadow-lg shadow-teal-500/10'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40 border border-transparent'
                }`}
              >
                <div className="flex items-center gap-2 font-semibold text-xs sm:text-sm">
                  <span className={isActive ? 'text-teal-400' : 'text-slate-400'}>
                    {tab.icon}
                  </span>
                  <span>{tab.label}</span>
                </div>
                <span className="text-[10px] text-slate-400 mt-0.5 hidden sm:block">
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
