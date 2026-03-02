"""
Uses an LLM to produce human-readable incident summaries from a batch of events.
Falls back to a template-based summary when no API key is configured.
"""

from __future__ import annotations

import datetime
from collections import Counter
from typing import Optional

from loguru import logger
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from src.models.database import Event, IncidentSummary


class IncidentSummarizer:

    def __init__(self, db: AsyncSession):
        self._db = db

    async def generate_summary(
        self,
        period_start: datetime.datetime,
        period_end: datetime.datetime,
        camera_ids: Optional[list[int]] = None,
    ) -> IncidentSummary:
        filters = [
            Event.timestamp >= period_start,
            Event.timestamp <= period_end,
        ]
        if camera_ids:
            filters.append(Event.camera_id.in_(camera_ids))

        result = await self._db.execute(select(Event).where(and_(*filters)).order_by(Event.timestamp))
        events = result.scalars().all()

        if settings.openai_api_key:
            summary_text = await self._llm_summary(events, period_start, period_end)
        else:
            summary_text = self._template_summary(events, period_start, period_end)

        summary = IncidentSummary(
            period_start=period_start,
            period_end=period_end,
            summary_text=summary_text,
            event_count=len(events),
            camera_ids=[e.camera_id for e in events],
        )
        self._db.add(summary)
        await self._db.flush()
        logger.info(f"Generated incident summary: {len(events)} events from {period_start} to {period_end}")
        return summary

    def _template_summary(
        self,
        events: list[Event],
        period_start: datetime.datetime,
        period_end: datetime.datetime,
    ) -> str:
        if not events:
            return f"No incidents recorded between {period_start:%Y-%m-%d %H:%M} and {period_end:%Y-%m-%d %H:%M}."

        type_counts = Counter(e.event_type for e in events)
        severity_counts = Counter(e.severity for e in events)
        camera_ids = sorted(set(e.camera_id for e in events))

        lines = [
            f"Incident Summary: {period_start:%Y-%m-%d %H:%M} – {period_end:%Y-%m-%d %H:%M}",
            f"Total events: {len(events)}",
            "",
            "By type:",
        ]
        for etype, cnt in type_counts.most_common():
            lines.append(f"  - {etype}: {cnt}")

        lines.append("")
        lines.append("By severity:")
        for sev, cnt in severity_counts.most_common():
            lines.append(f"  - {sev}: {cnt}")

        lines.append("")
        lines.append(f"Cameras involved: {', '.join(str(c) for c in camera_ids)}")

        critical = [e for e in events if e.severity == "critical"]
        if critical:
            lines.append("")
            lines.append("Critical incidents:")
            for e in critical[:5]:
                lines.append(f"  [{e.timestamp:%H:%M}] Camera {e.camera_id}: {e.description}")

        return "\n".join(lines)

    async def _llm_summary(
        self,
        events: list[Event],
        period_start: datetime.datetime,
        period_end: datetime.datetime,
    ) -> str:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.openai_api_key)

            event_lines = []
            for e in events[:100]:
                event_lines.append(
                    f"[{e.timestamp:%H:%M}] Camera {e.camera_id} | {e.event_type} | "
                    f"{e.severity} | {e.description}"
                )

            prompt = (
                f"You are a facility security AI assistant. Summarise the following {len(events)} "
                f"security/operations events from {period_start:%Y-%m-%d %H:%M} to {period_end:%Y-%m-%d %H:%M}.\n"
                f"Provide a concise management-level summary with key findings, patterns, and recommendations.\n\n"
                + "\n".join(event_lines)
            )

            response = await client.chat.completions.create(
                model=settings.openai_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
            )
            return response.choices[0].message.content or self._template_summary(events, period_start, period_end)
        except Exception as e:
            logger.error(f"LLM summary failed, falling back to template: {e}")
            return self._template_summary(events, period_start, period_end)
