# iClinic - Requirements Checklist

Status key: **Met** = built and tried against the running app. **Met (simulated)** = built and tried, but not over the real
channel. **Open** = not done.

## Functional requirements

| ID | Requirement | Status | How it is met / how it was checked |
|---|---|---|---|
| FR-1 | Voice Assistant and AI Outbound Calls | Met (simulated for calls) | Browser voice assistant tested with real speech-to-text and text-to-speech (English, Tamil, Telugu). Outbound call turns tested through the same turn handler Twilio uses; a real phone dial-out was not placed. |
| FR-2 | Chat interface | Met | Web chat tab; full book / reschedule / cancel journey tested. |
| FR-3 | Voice flow: greeting, intent, appointment type, provider, slots, confirm date and time, confirm booking, send confirmation | Met | The type is asked on every channel (voice, call, chat) before booking. |
| FR-4 | Natural conversation: interruptions and corrections | Met for corrections; interruptions in the browser voice overlay only | Corrections (date, time, provider, type) accepted without restarting. Phone-call barge-in depends on Twilio and was not tested. |
| FR-5 | Outbound call flow | Met (simulated) | Identify, provider preference, slots, book, confirm - run through the outbound turn handler. |
| FR-6 | Identity confirmation (name and date of birth) | Met | Two failed attempts end with no booking and a hand-off to the front desk. |
| FR-7 | Offer available slots | Met | Slots come only from the clinic schedule tables. Day listings are spoken by time of day (morning / afternoon / evening). |
| FR-8 | Alternate slots: nearest times, same provider, next provider | Met | Nearest times on the same day, the same doctor's other days, and "any other doctor" lists the next available providers. |
| FR-9 | Reconfirm date and time, provider, location and type before booking | Met | "Just to confirm: a <type> with <doctor> at our <branch> branch on <date and time>. Shall I book it?" |
| FR-10 | Confirm in the conversation | Met | The booking reply states doctor, branch, date and time. |
| FR-11 | SMS / email confirmation | Met | Email delivered. SMS is delivered only to numbers the Twilio account may text (a Twilio trial account refuses unverified numbers). |
| FR-12 | Confirmation content | Met | Date and time, doctor, branch, appointment type and instructions, in both SMS and email. |
| FR-13 | Chat flow: greeting, reason, appointment types, slots, confirm, confirmation | Met | The reason is asked and the types are listed from the database. |
| FR-14 | Minimum booking inputs | Met | Reason, type, date and time, provider preference, and identity check. |

## Logging and error handling

| Item | Status | Notes |
|---|---|---|
| Conversation state log with date and time for every change | Met | Started, Identifying patient, Collecting details, Suggesting slots, Slot reserved, Reconfirming, Booked, Confirmation sent, plus Rescheduled, Cancelled, Abandoned, Failed, Handed to front desk, No answer, Busy, Retry scheduled. |
| Step-by-step log: input, output, time taken, result | Met | One entry per message with what the patient said (personal data removed), the reply, milliseconds, and success / warning / error. |
| Open any conversation to see timeline and transcript | Met | Front desk Conversations tab. |
| Speech not understood: ask again, then offer transfer | Met (chat tested; voice built but not run live) | Voice: a second failure offers the front desk. Chat and calls: a second "not understood" offers the front desk. |
| Patient not reached / wrong person (outbound) | Met (simulated) | No answer, busy and retry are tracked. "Wrong number" ends the call politely with outcome "wrong person" and no booking. |
| Identity not confirmed: do not book, hand to front desk | Met | |
| Slot taken before booking: offer alternates | Met | |
| SMS/email failure: retry, then flag | Met | Retries up to 3 times (stops at once on a permanent refusal). The conversation is flagged if any message could not be delivered; the email still goes out. |
| No half-made bookings | Met | Slot holds expire; booking and slot change in one transaction. |
| Odd input: nonsense names, bare yes / no, walking away, past dates, booking for someone else, two-digit birth year | Met | Each gets a clear reply and never starts or changes a booking by accident. |
| Schedule source unavailable | Partly met | The patient hears a polite apology; staff see the error in the step log and server log. |
| Filters: channel, date range, provider, type, location, state, confirmation status | Met | Appointments and Conversations screens. |
| Sorting: appointment date, booking time, provider, state | Met | |

## Scenarios

| # | Scenario | Result |
|---|---|---|
| 1 | Voice booking, slot available | Passed |
| 2 | Voice booking, slot unavailable, alternates | Passed |
| 3 | Correction mid-flow | Passed |
| 4 | Outbound call end to end | Passed (simulated call) |
| 5 | Chat booking end to end | Passed |
| 6 | Chat alternates and corrections | Passed |
| 7 | Outbound identity not confirmed | Passed |
| 8 | SMS fails, retry, email sent, flagged | Passed (observed with the Twilio trial restriction) |

## Success measures

| Measure | Target | Status |
|---|---|---|
| Conversations with full state and step log | 100% | New conversations: yes. Conversations from before the step log existed have a shorter log. |
| Confirmations with all FR-12 details | 100% | Yes for new bookings. |
| Half-made or double bookings | None | None seen. One database gap is listed in LIMITATIONS.md. |
| Running on the cloud | Working | **Open** - deployment is not part of this hand-over yet. |
