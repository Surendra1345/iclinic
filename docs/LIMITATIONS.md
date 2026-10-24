# Limitations and next steps

## Limitations
- **Cloud:** the assistant has not been deployed to the cloud, and deployment instructions are not written yet.
- **Real phone calls:** outbound call turns were tested through the shared turn handler. A real Twilio dial-out, phone-line
  speech recognition and barge-in were not tested.
- **Text messages:** a Twilio trial account only texts verified numbers. Other numbers fail; the failure is logged, the
  email still goes out, and the conversation is flagged.
- **AI model quota and speed:** on the free Gemini tier each model allows about 20 requests a day. Replies that need the
  model take 2-7 seconds; when it is unavailable the agent falls back to built-in rules (booking still works, clinic
  questions get plainer answers, and Tamil / Telugu cannot be translated). Enabling billing fixes this.
- **Tamil and Telugu:** voice only. The web chat is English only. The first Tamil / Telugu turn after a quiet period can take
  15-20 seconds.
- **Sarvam credits:** speech to text and text to speech need Sarvam credit. When the balance ran out during testing the voice assistant could not speak or listen, and the browser's own voice is the fallback. Keep the balance topped up.
- **Speech recognition:** branch names are sometimes misheard (for example "Annagar").
- **Database:** the unique indexes that stop two active appointments for one patient count only "booked" appointments, not
  "rescheduled" ones. The application checks both, so this is only a safety net that is missing. Changing it needs a
  database migration, which was deliberately not made.
- **Older data:** conversations recorded before this version show a confirmation status of "sent" even when nothing was
  sent, and older appointments are marked as outbound-call bookings. New records are correct.
- **Booking for someone else:** the assistant books only for the verified patient. A request such as "for my mother" is explained and offered to the front desk instead.
- **Access control:** the front desk dashboard needs a login. The patient chat, voice endpoints and Twilio webhooks are open
  by design; restrict access at the cloud level. The outbound-call allowlist (`OUTBOUND_CALL_ALLOWED_NUMBERS`) does nothing
  until it is set.
- **Login:** one shared front desk account with a simple password; the login attempt limit is per server process.

## Next steps
1. Deploy to the approved cloud environment, set the front desk password, secret and call allowlist, and restrict public access.
2. Enable Gemini billing (or approved models) and rotate the API key that was shared during development.
3. Verify the Twilio sender and test numbers; run each scenario on a real phone call.
4. Add the database index change for "rescheduled" appointments and repair old records, once approved.
5. Add chat support for Tamil and Telugu, and a way for a parent or guardian to book for a family member under clinic policy.
