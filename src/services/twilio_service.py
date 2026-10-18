"""Twilio service — generate TwiML responses and send SMS notifications."""
import logging
import time
from typing import Optional
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream

from src.config.settings import settings
from src.observability.metrics import provider_request_duration_seconds

logger = logging.getLogger(__name__)


class TwilioService:

    def __init__(self):
        self.account_sid = settings.TWILIO_ACCOUNT_SID
        self.auth_token = settings.TWILIO_AUTH_TOKEN
        self.phone_number = settings.TWILIO_PHONE_NUMBER
        self._client: Optional[Client] = None

    @property
    def client(self) -> Client:
        if self._client is None:
            if not self.account_sid or not self.auth_token:
                raise ValueError("Twilio credentials (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN) not set.")
            self._client = Client(self.account_sid, self.auth_token)
        return self._client

    def initiate_outbound_call(
        self,
        to_phone: str,
        webhook_url: str,
        status_callback_url: Optional[str] = None,
    ) -> str:
        """
        Initiate an outbound phone call using Twilio REST API.
        Twilio dials `to_phone` from clinic's `phone_number`.
        When answered, Twilio fetches TwiML from `webhook_url`.
        """
        if not self.phone_number:
            raise ValueError("Twilio TWILIO_PHONE_NUMBER is not set.")

        logger.info(f"Initiating outbound call to {to_phone} from {self.phone_number} with webhook {webhook_url}")
        call_kwargs = {
            "to": to_phone,
            "from_": self.phone_number,
            "url": webhook_url,
        }
        if status_callback_url:
            call_kwargs["status_callback"] = status_callback_url
        started = time.perf_counter()
        try:
            call = self.client.calls.create(**call_kwargs)
        finally:
            provider_request_duration_seconds.labels("twilio", "create_call").observe(
                time.perf_counter() - started
            )
        logger.info(f"Outbound call initiated successfully. CallSid: {call.sid}")
        return call.sid

    def get_call_status(self, call_sid: str) -> str:
        """Read the current provider status for a call when a callback was missed."""
        started = time.perf_counter()
        try:
            return str(self.client.calls(call_sid).fetch().status or "").lower()
        finally:
            provider_request_duration_seconds.labels("twilio", "get_call_status").observe(
                time.perf_counter() - started
            )

    def build_stream_twiml(
        self,
        websocket_url: str,
        custom_parameters: Optional[dict] = None,
        status_callback: Optional[str] = None,
    ) -> str:
        """
        Build TwiML response to connect call audio to a WebSocket media stream.
        Uses Twilio's standard <Parameter> tags for clean parameter passing without URL corruption.
        """
        response = VoiceResponse()
        connect = Connect()
        stream_kwargs = {"url": websocket_url}
        if status_callback:
            stream_kwargs["status_callback"] = status_callback

        stream = Stream(**stream_kwargs)
        if custom_parameters:
            for k, v in custom_parameters.items():
                if v is not None and str(v).strip():
                    stream.parameter(name=k, value=str(v).strip())
        connect.append(stream)
        response.append(connect)
        return str(response)

    def build_handoff_twiml(self, message: str, phone_number: str) -> str:
        """
        Build TwiML to speak a handoff message and transfer call to front desk.
        """
        response = VoiceResponse()
        if message:
            response.say(message, voice="Polly.Aditi", language="en-IN")
        if phone_number:
            response.dial(phone_number)
        else:
            response.hangup()
        return str(response)

    def build_hangup_twiml(self, message: Optional[str] = None) -> str:
        """
        Build TwiML to speak goodbye message and hang up.
        """
        response = VoiceResponse()
        if message:
            response.say(message, voice="Polly.Aditi", language="en-IN")
        response.hangup()
        return str(response)

    def send_sms(self, to_phone: str, body: str) -> dict:
        """
        Send an SMS notification via Twilio REST API.
        """
        if not self.account_sid or not self.auth_token or not self.phone_number:
            logger.warning("Twilio SMS credentials not configured. Skipping SMS.")
            return {"status": "skipped", "reason": "Twilio not configured"}

        try:
            started = time.perf_counter()
            msg = self.client.messages.create(
                to=to_phone,
                from_=self.phone_number,
                body=body,
            )
            provider_request_duration_seconds.labels("twilio", "send_sms").observe(
                time.perf_counter() - started
            )
            return {"sid": msg.sid, "status": msg.status}
        except Exception as e:
            provider_request_duration_seconds.labels("twilio", "send_sms").observe(
                time.perf_counter() - started
            )
            logger.error(f"Failed to send SMS to {to_phone}: {e}")
            raise
