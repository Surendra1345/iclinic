from enum import Enum


class ChannelType(str, Enum):
    VOICE = "voice"
    OUTBOUND_CALL = "outbound_call"
    CHAT = "chat"


class SlotStatus(str, Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    BOOKED = "booked"


class AppointmentStatus(str, Enum):
    BOOKED = "booked"
    RESCHEDULED = "rescheduled"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class ConversationState(str, Enum):
    STARTED = "started"
    IDENTIFYING_PATIENT = "identifying_patient"
    COLLECTING_DETAILS = "collecting_details"
    SUGGESTING_SLOTS = "suggesting_slots"
    SLOT_RESERVED = "slot_reserved"
    RECONFIRMING = "reconfirming"
    BOOKED = "booked"
    ABANDONED = "abandoned"
    FAILED = "failed"
    HANDED_TO_FRONT_DESK = "handed_to_front_desk"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    RETRY_SCHEDULED = "retry_scheduled"


class OutcomeType(str, Enum):
    BOOKED = "booked"
    ABANDONED = "abandoned"
    FAILED = "failed"
    HANDED_TO_FRONT_DESK = "handed_to_front_desk"
    NOT_REACHED = "not_reached"
    WRONG_PERSON = "wrong_person"


class ConfirmationStatusType(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    RETRYING = "retrying"
    FAILED = "failed"
    FLAGGED = "flagged"


class OutboundCallRequestStatus(str, Enum):
    WAITING = "waiting"
    PROCESSING = "processing"
    STARTED = "started"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"


class CallStatus(str, Enum):
    DIALING = "dialing"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    ANSWERED = "answered"
    FAILED = "failed"


class NotificationChannel(str, Enum):
    SMS = "sms"
    EMAIL = "email"


class NotificationStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class PatientSource(str, Enum):
    ASSISTANT = "assistant"
    FRONT_DESK = "front_desk"
