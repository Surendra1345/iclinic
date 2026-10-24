# iClinic - Results report

## What was built
A conversational front desk assistant for a four-branch clinic, available as a web chat, a browser voice assistant
(English, Tamil, Telugu) and AI outbound calls. It books, reschedules and cancels appointments from the clinic's own
doctor and slot data, answers clinic questions from that data, confirms by SMS and email, and never gives medical advice.
Front desk staff sign in to a dashboard with appointments, patients, conversations and forwarded requests.

## Test summary
- **Automated tests:** 206 passed, 1 skipped (the chat end-to-end file, which only runs against a separate test database).
- **Live checks against the running app** (real database, Gemini and Sarvam):
  - About 30 clinic questions (branches and addresses, doctors, specialties, appointment types, policies, open slots,
    slot counts, earliest slot) answered correctly from the data. Emergency symptoms and unrelated questions are handled safely.
  - Chat: book, change doctor and time, reschedule, cancel, one-active-appointment rule, visit type reconfirmation.
  - Voice: English, Tamil and Telugu with real speech-to-text and text-to-speech.
  - Outbound call: booking through the outbound turn handler.
  - Error paths: wrong date of birth twice (no booking, hand-off), SMS refused (email sent, conversation flagged),
    nearest-time alternates, correction mid-flow.

## Measures
| Measure | Result |
|---|---|
| Scenarios 1-8 | All pass (calls simulated through the turn handler) |
| Bookings with correct details | Correct doctor, branch, time, type and channel in every test booking |
| Confirmations with all required details | Yes (doctor, branch, date and time, type, instructions) |
| Half-made or double bookings | None |
| Conversations with state and step log | All new conversations |
| Replies without the AI model | 0.5-0.7 s; with the AI model 2-7 s |
| Cloud | Not deployed yet |

See `FR_CHECKLIST.md` for each requirement and `LIMITATIONS.md` for known limits and next steps.
