import { ENV } from '../../../config/env'

const MASCULINE_VOICE_NAME = /\b(male|man|masculine|david|mark|guy|daniel|james|george|brian|ryan|alex|aaron|tom|thomas|fred|jorge|diego|rishi|kabir|aditya)\b/i
const FEMININE_VOICE_NAME = /\b(female|woman|feminine|zira|heera|samantha|karen|susan|victoria|ava|allison|joanna|kendra|kimberly|salli|tessa|veena)\b/i

/** Choose a browser voice that is likely masculine; Web Speech has no gender field. */
export function selectMaleSpeechVoice(voices: SpeechSynthesisVoice[], language: string) {
  const languagePrefix = language.slice(0, 2).toLowerCase()
  const sameLanguage = voices.filter((voice) =>
    voice.lang.toLowerCase() === language.toLowerCase(),
  )
  const sameLanguagePrefix = voices.filter((voice) =>
    voice.lang.toLowerCase().startsWith(languagePrefix),
  )
  const likelyMale = (voice: SpeechSynthesisVoice) =>
    MASCULINE_VOICE_NAME.test(voice.name) && !FEMININE_VOICE_NAME.test(voice.name)
  const notExplicitlyFeminine = (voice: SpeechSynthesisVoice) =>
    !FEMININE_VOICE_NAME.test(voice.name)

  return (
    sameLanguage.find(likelyMale) ||
    sameLanguagePrefix.find(likelyMale) ||
    sameLanguage.find(notExplicitlyFeminine) ||
    sameLanguagePrefix.find(notExplicitlyFeminine) ||
    voices.find(likelyMale) ||
    sameLanguage[0] ||
    sameLanguagePrefix[0] ||
    voices.find((voice) => /google|natural/i.test(voice.name)) ||
    voices[0]
  )
}
/** Resolve API-provided relative audio paths against the configured backend URL. */
export function resolveVoiceAudioUrl(audioUrl: string) {
  return new URL(audioUrl, ENV.API_BASE_URL || window.location.origin).toString()
}
