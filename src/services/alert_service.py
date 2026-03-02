"""
Dispatches alerts via email, webhook, or dashboard notifications.
"""

from __future__ import annotations

import datetime
from typing import Optional

import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from src.models.database import Alert, Event
from src.services.anomaly_detector import AnomalyEvent


class AlertService:

    def __init__(self, db: AsyncSession):
        self._db = db

    async def dispatch(self, event_id: int, anomaly: AnomalyEvent) -> list[Alert]:
        """Send alerts for an anomaly event through all configured channels."""
        alerts: list[Alert] = []

        alerts.append(await self._send_dashboard_alert(event_id, anomaly))

        if settings.smtp_host:
            for recipient in self._parse_recipients():
                alert = await self._send_email_alert(event_id, anomaly, recipient)
                if alert:
                    alerts.append(alert)

        return alerts

    def _parse_recipients(self) -> list[str]:
        raw = settings.alert_recipients
        if not raw:
            return []
        return [r.strip() for r in raw.split(",") if r.strip()]

    async def _send_dashboard_alert(self, event_id: int, anomaly: AnomalyEvent) -> Alert:
        alert = Alert(
            event_id=event_id,
            channel="dashboard",
            recipient="dashboard",
            status="sent",
            sent_at=datetime.datetime.utcnow(),
        )
        self._db.add(alert)
        await self._db.flush()
        return alert

    async def _send_email_alert(self, event_id: int, anomaly: AnomalyEvent, recipient: str) -> Optional[Alert]:
        alert = Alert(
            event_id=event_id,
            channel="email",
            recipient=recipient,
            status="pending",
        )
        try:
            import aiosmtplib
            from email.message import EmailMessage

            msg = EmailMessage()
            msg["Subject"] = f"[VisionAI] {anomaly.severity.upper()}: {anomaly.event_type}"
            msg["From"] = settings.smtp_user
            msg["To"] = recipient
            msg.set_content(
                f"Camera: {anomaly.camera_id}\n"
                f"Type: {anomaly.event_type}\n"
                f"Severity: {anomaly.severity}\n"
                f"Description: {anomaly.description}\n"
                f"Time: {anomaly.timestamp.isoformat()}\n"
            )

            await aiosmtplib.send(
                msg,
                hostname=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_user,
                password=settings.smtp_password,
                start_tls=True,
            )
            alert.status = "sent"
            alert.sent_at = datetime.datetime.utcnow()
            logger.info(f"Email alert sent to {recipient} for event {event_id}")
        except Exception as e:
            alert.status = "failed"
            logger.error(f"Email alert failed for {recipient}: {e}")

        self._db.add(alert)
        await self._db.flush()
        return alert

    async def send_webhook(self, url: str, event_id: int, anomaly: AnomalyEvent) -> None:
        payload = {
            "event_id": event_id,
            "event_type": anomaly.event_type,
            "severity": anomaly.severity,
            "description": anomaly.description,
            "camera_id": anomaly.camera_id,
            "timestamp": anomaly.timestamp.isoformat(),
            "metadata": anomaly.metadata,
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, timeout=10)
                resp.raise_for_status()
            logger.info(f"Webhook sent to {url} for event {event_id}")
        except Exception as e:
            logger.error(f"Webhook failed for {url}: {e}")
