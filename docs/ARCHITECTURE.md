# iClinic - Architecture and sequence diagrams

The diagrams are written in Mermaid. They show as pictures on GitHub, and in VS Code with the "Markdown Preview Mermaid
Support" extension (or any Mermaid viewer).

## 1. System architecture

```mermaid
flowchart LR
    subgraph Patient["Patient channels"]
        WEB["Web chat and browser voice<br/>React page /patients"]
        PHONE["Patient's phone"]
    end

    subgraph Staff["Front desk"]
        DASH["Dashboard /frontdesk<br/>(login required)"]
    end

    subgraph Backend["FastAPI backend"]
        ROUTES["REST routes<br/>/api/chat, /api/voice-assistant<br/>/api/calls/trigger, /twilio/*<br/>/api/auth, /api/dashboard/*"]
        TURN["Conversation turn service<br/>(one turn: save, run agent, save)"]
        AGENT["LangGraph agent<br/>(state machine + guards)"]
        NOTIFY["Notification service<br/>(retry, then flag)"]
        SCHED["Scheduler<br/>outbound retries, call reconcile,<br/>slot-hold cleanup"]
        DEFER["Deferred jobs<br/>(start after the turn is saved)"]
    end

    subgraph External["External services"]
        GEMINI["Gemini<br/>intent, clinic answers, translation"]
        SARVAM["Sarvam<br/>speech to text, text to speech"]
        TWILIO["Twilio<br/>calls and SMS"]
        SMTP["SMTP<br/>email"]
    end

    DB[("PostgreSQL<br/>clinic data, patients, slots, appointments,<br/>conversations, notifications,<br/>agent checkpoints")]

    WEB -->|"text / audio"| ROUTES
    PHONE <-->|"voice"| TWILIO
    TWILIO <-->|"webhooks (signed)"| ROUTES
    DASH -->|"token"| ROUTES
    ROUTES --> TURN --> AGENT
    ROUTES -->|"transcribe / speak"| SARVAM
    AGENT --> GEMINI
    AGENT <--> DB
    TURN <--> DB
    ROUTES <--> DB
    TURN --> DEFER --> NOTIFY
    NOTIFY --> TWILIO
    NOTIFY --> SMTP
    NOTIFY --> DB
    SCHED --> TWILIO
    SCHED <--> DB
```

**Reading it:** every channel ends up in the same turn service and the same agent, so chat, voice and calls share one set
of booking rules. The database is the only source of doctors, branches and slots; nothing about the clinic is hard-coded.

## 2. Inside the agent (one patient message)

```mermaid
flowchart TD
    START([patient message]) --> S[start<br/>reset per-turn flags]
    S -->|emergency or handoff in progress| H[handoff to front desk]
    S -->|"identity words, or unverified"| ID[identity<br/>name + date of birth]
    S -->|new patient| REG[register]
    S -->|no speech on a call| G[greet]
    S --> DI[detect intent]

    DI -->|"answer ready<br/>(yes/no, ok, past date, walk away...)"| END1([reply])
    DI -->|clinic question| FAQ[faq<br/>answer from database facts]
    DI -->|book| B[booking]
    DI -->|reschedule| R[reschedule]
    DI -->|cancel| C[cancel]
    DI -->|"unverified patient wants an action"| ID
    DI -->|goodbye| E[end call<br/>record outcome]
    DI -->|handoff| H

    ID -->|verified| DI
    ID -->|too many failures| H
    ID --> END1
    REG --> END1

    B -->|booked| CONF[confirmation]
    R -->|rescheduled| CONF
    C -->|cancelled| CONF
    B --> END1
    R --> END1
    C --> END1
    B -->|booking failed| H
    FAQ --> END1
    CONF -->|"SMS + email queued"| E
    H --> END1
    E --> END2([turn ends, outcome saved])
    G --> END1
```

Between turns the agent's state (identity, held slot, chosen doctor and date, what it is waiting for) is kept in the
database, so each message continues where the last one stopped.

## 3. Sequence: booking in the web chat

```mermaid
sequenceDiagram
    autonumber
    actor P as Patient
    participant UI as Chat page
    participant API as /api/chat
    participant T as Turn service
    participant A as Agent
    participant G as Gemini
    participant DB as PostgreSQL
    participant N as Notification (background)

    P->>UI: "book a cardiology appointment"
    UI->>API: message + session id
    API->>T: run turn
    T->>A: invoke
    A->>G: classify intent (rules if Gemini is slow)
    A-->>T: "please give name and date of birth"
    T->>DB: save message, state, step log
    API-->>UI: reply
    P->>UI: name + date of birth
    A->>DB: match patient record
    A-->>UI: verified, which branch, doctor or date?
    P->>UI: "Anna Nagar Tuesday"
    A->>DB: read open slots
    A-->>UI: times grouped by doctor + tap buttons
    P->>UI: taps a time
    A->>DB: hold the slot (reserved for a few minutes)
    A-->>UI: "held, shall I book it?" + Yes / No
    P->>UI: Yes
    A-->>UI: "reason for your visit?" + visit-type buttons
    P->>UI: taps "General Consultation"
    A-->>UI: "Just to confirm: type, doctor, branch, time. Shall I book it?"
    P->>UI: Yes
    A->>DB: book slot + create appointment (one transaction)
    A-->>T: booked, confirmation queued
    T->>DB: save turn, state "booked"
    API-->>UI: "booked, I am sending a confirmation..."
    T-)N: start after the turn is saved
    N->>N: SMS and email, retry up to 3 times
    N->>DB: notification rows, status SENT or FLAGGED,<br/>state "confirmation sent"
```

## 4. Sequence: one voice turn (browser voice assistant)

```mermaid
sequenceDiagram
    autonumber
    actor P as Patient
    participant UI as Voice overlay
    participant API as /api/voice-assistant/turn
    participant S as Sarvam
    participant G as Gemini
    participant T as Turn service + Agent
    participant DB as PostgreSQL

    P->>UI: speaks
    UI->>API: audio + session id
    API->>S: speech to text
    alt nothing understood
        API-->>UI: "please speak again" (after 2 failures: offer the front desk)
    else transcript
        opt Tamil or Telugu, or an Indian script in an English session
            API->>G: translate to English (common yes / no / thanks handled offline)
        end
        API->>T: run turn (English text)
        T->>DB: load state, read slots, save turn
        T-->>API: reply text
        opt Tamil or Telugu and the reply is not already localized
            API->>G: translate reply (retry once)
        end
        API->>S: text to speech
        S-->>API: audio
        API-->>UI: reply text + audio
        UI-->>P: speaks the reply
    end
```

## 5. Sequence: AI outbound call

```mermaid
sequenceDiagram
    autonumber
    actor Staff as Staff or API caller
    participant API as /api/calls/trigger
    participant DB as PostgreSQL
    participant TW as Twilio
    actor P as Patient (phone)
    participant WH as /twilio/voice and /twilio/agent-turn
    participant T as Turn service + Agent
    participant S as Sarvam

    Staff->>API: phone number
    API->>API: check allowlist, number format
    API->>DB: patient lookup, conversation, call record
    API->>TW: place the call
    TW->>P: rings
    alt no answer or busy
        TW->>WH: call status
        WH->>DB: state "no answer" / "busy", retry scheduled
    else answered
        TW->>WH: voice webhook (signature checked)
        WH->>S: speak the greeting
        WH-->>TW: play audio, listen
        loop until the call ends
            P->>TW: speaks
            TW->>WH: speech result
            WH->>T: run turn
            T->>DB: identity, slots, booking, logs
            T-->>WH: reply
            WH->>S: text to speech
            WH-->>TW: play reply, listen again
        end
        Note over WH,T: wrong person: call ends, outcome "wrong person"<br/>identity fails twice: no booking, hand-off to front desk
        TW->>WH: call status completed
        WH->>DB: close conversation, outcome
    end
```

## 6. Sequence: confirmation delivery and the failure path

```mermaid
sequenceDiagram
    autonumber
    participant T as Turn service
    participant J as Background job
    participant N as Notification service
    participant TW as Twilio (SMS)
    participant M as SMTP (email)
    participant DB as PostgreSQL

    T->>DB: commit the turn (appointment is saved)
    T-)J: start confirmation job
    J->>N: send SMS (branch, type, instructions, time)
    N->>TW: send
    alt fails
        TW--xN: error
        N->>N: retry up to 3 times (stops at once on a permanent refusal)
        N->>DB: notification row "failed" + reason
    else ok
        TW-->>N: accepted
        N->>DB: notification row "sent"
    end
    J->>N: send email (same details)
    N->>M: send
    M-->>N: accepted
    N->>DB: notification row "sent"
    J->>DB: any message failed: confirmation "flagged"<br/>all delivered: "sent" and state "confirmation sent"
```

## 7. Sequence: front desk dashboard

```mermaid
sequenceDiagram
    autonumber
    actor Staff as Front desk
    participant UI as /frontdesk
    participant API as /api/auth and /api/dashboard
    participant DB as PostgreSQL

    Staff->>UI: opens /frontdesk
    UI->>UI: no token, go to the login page
    Staff->>UI: email + password
    UI->>API: POST /api/auth/login
    API-->>UI: signed token (8 hours), 5 failed tries lock for 5 minutes
    loop every 5 seconds
        UI->>API: GET appointments / conversations / patients (Bearer token)
        API->>DB: query with filters and sorting
        API-->>UI: rows (times shown in IST)
    end
    Staff->>UI: opens a conversation
    UI->>API: GET conversation detail
    API-->>UI: transcript, state timeline, step log
    Note over UI,API: a 401 clears the token and returns to the login page
```
