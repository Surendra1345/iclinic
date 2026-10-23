"""Notification service — handles SMS and email confirmations and staff alerts."""
import asyncio
import logging
import smtplib
import uuid
from email.message import EmailMessage
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.constants.enums import NotificationChannel, NotificationStatus
from src.data.repositories.notification_repository import NotificationRepository
from src.services.twilio_service import TwilioService

logger = logging.getLogger(__name__)


class NotificationService:

    def __init__(self, db: AsyncSession, twilio_service: Optional[TwilioService] = None):
        self.db = db
        self.notification_repo = NotificationRepository(db)
        self.twilio_service = twilio_service or TwilioService()

    async def send_confirmation_sms(
        self,
        *,
        appointment_id: uuid.UUID,
        to_phone: str,
        patient_name: str,
        doctor_name: str,
        start_time_str: str,
        action: str = "booked",  # "booked" | "rescheduled" | "cancelled"
    ) -> bool:
        """Send appointment SMS confirmation and log to DB."""
        if action == "booked":
            message = (
                f"Hello {patient_name}, your appointment with {doctor_name} at "
                f"{settings.CLINIC_NAME} is confirmed for {start_time_str}. "
                f"To reschedule or cancel, reply to this text or call us."
            )
        elif action == "rescheduled":
            message = (
                f"Hello {patient_name}, your appointment with {doctor_name} has been "
                f"rescheduled to {start_time_str}. Thank you, {settings.CLINIC_NAME}."
            )
        else:
            message = (
                f"Hello {patient_name}, your appointment with {doctor_name} on "
                f"{start_time_str} has been cancelled. Thank you, {settings.CLINIC_NAME}."
            )

        # Log pending notification in DB
        notif = await self.notification_repo.create_notification(
            appointment_id=appointment_id,
            channel=NotificationChannel.SMS,
            recipient=to_phone,
            status=NotificationStatus.PENDING,
        )

        try:
            resp = self.twilio_service.send_sms(to_phone, message)
            await self.notification_repo.mark_sent(notif.id, provider_response=resp)
            return True
        except Exception as e:
            logger.error("Failed to deliver SMS to %s: %s", to_phone, e)
            await self.notification_repo.mark_failed(notif.id, error_detail=str(e))
            return False

    async def send_confirmation_email(
        self,
        *,
        appointment_id: uuid.UUID,
        to_email: str,
        patient_name: str,
        doctor_name: str,
        start_time_str: str,
        action: str = "booked",
    ) -> bool:
        """Send an appointment email through the configured SMTP server."""
        notif = await self.notification_repo.create_notification(
            appointment_id=appointment_id,
            channel=NotificationChannel.EMAIL,
            recipient=to_email,
        )
        try:
            if not all(
                [
                    settings.SMTP_HOST,
                    settings.SMTP_USERNAME,
                    settings.SMTP_PASSWORD,
                    settings.SMTP_FROM_EMAIL,
                ]
            ):
                raise RuntimeError(
                    "SMTP email is not configured; set SMTP_HOST, SMTP_USERNAME, "
                    "SMTP_PASSWORD, and SMTP_FROM_EMAIL"
                )

            subject, body = self._build_email_content(
                patient_name=patient_name,
                doctor_name=doctor_name,
                start_time_str=start_time_str,
                action=action,
            )
            response = await asyncio.to_thread(
                self._send_smtp_email,
                to_email,
                subject,
                body,
            )
            await self.notification_repo.mark_sent(notif.id, provider_response=response)
            return True
        except Exception as e:
            logger.error("Failed to deliver email to %s: %s", to_email, e)
            await self.notification_repo.mark_failed(notif.id, error_detail=str(e))
            return False

    @staticmethod
    def _build_email_content(
        *,
        patient_name: str,
        doctor_name: str,
        start_time_str: str,
        action: str,
    ) -> tuple[str, str]:
        if action == "booked":
            subject = "Appointment confirmed"
            opening = "Your appointment has been booked."
        elif action == "rescheduled":
            subject = "Appointment rescheduled"
            opening = "Your appointment has been rescheduled."
        else:
            subject = "Appointment cancelled"
            opening = "Your appointment has been cancelled."

        body = (
            f"Hello {patient_name},\n\n"
            f"{opening}\n\n"
            f"Doctor: {doctor_name}\n"
            f"Clinic: {settings.CLINIC_NAME}\n"
            f"Appointment time: {start_time_str}\n\n"
            f"Thank you,\n{settings.CLINIC_NAME}"
        )
        return subject, body

    @staticmethod
    def _send_smtp_email(to_email: str, subject: str, body: str, timeout_seconds: int = 20) -> dict:
        message = EmailMessage()
        message["From"] = settings.SMTP_FROM_EMAIL
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)

        if settings.SMTP_PORT == 465:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout_seconds) as server:
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                server.send_message(message)
        else:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout_seconds) as server:
                server.ehlo()
                if settings.SMTP_USE_TLS:
                    server.starttls()
                    server.ehlo()
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                server.send_message(message)

        return {"status": "sent", "provider": "smtp"}

    async def send_frontdesk_alert_email(
        self,
        *,
        reason: str,
        call_details: dict,
    ) -> bool:
        """Email front desk a callback-ready escalation; never include DOB."""
        recipient = (settings.FRONT_DESK_EMAIL or "").strip()
        if not recipient:
            logger.warning("Front desk escalation was queued without email: FRONT_DESK_EMAIL is not configured")
            return False
        if not all((settings.SMTP_HOST, settings.SMTP_USERNAME, settings.SMTP_PASSWORD, settings.SMTP_FROM_EMAIL)):
            logger.warning("Front desk escalation email is not configured: SMTP settings are incomplete")
            return False

        contact_phone = call_details.get("patient_phone") or "Not provided"
        contact_email = call_details.get("patient_email") or "Not provided"
        identity_status = "Verified" if call_details.get("identity_verified") else "Unverified"
        subject = f"Patient follow-up requested — {settings.CLINIC_NAME}"
        body = (
            "A patient conversation needs front-desk follow-up.\n\n"
            f"Reason: {reason}\n"
            f"Channel: {call_details.get('channel') or 'Unknown'}\n"
            f"Patient name: {call_details.get('patient_name') or 'Not provided'} ({identity_status})\n"
            f"Callback phone: {contact_phone}\n"
            f"Callback email: {contact_email}\n"
            f"Conversation ID: {call_details.get('conversation_id') or 'Not available'}\n"
            f"Call ID: {call_details.get('call_sid') or 'Not available'}\n\n"
            "Open the front-desk dashboard to review the conversation transcript."
        )
        try:
            result = await asyncio.to_thread(
                self._send_smtp_email,
                recipient,
                subject,
                body,
                5,
            )
            logger.info(
                "Front desk escalation email sent to %s for conversation %s",
                recipient,
                call_details.get("conversation_id"),
            )
            return result.get("status") == "sent"
        except Exception:
            logger.exception(
                "Failed to email front desk escalation for conversation %s",
                call_details.get("conversation_id"),
            )
            return False
