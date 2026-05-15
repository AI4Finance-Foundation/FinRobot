"""Email notification channel via SMTP."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.mime.text import MIMEText

from finagent.engine.notify.base import NotifyChannel, NotifyMessage

logger = logging.getLogger(__name__)


class EmailChannel(NotifyChannel):
    name = "email"

    def __init__(
        self,
        smtp_host: str | None = None,
        smtp_port: int = 587,
        smtp_user: str | None = None,
        smtp_pass: str | None = None,
        to_addr: str | None = None,
    ) -> None:
        self._host = smtp_host
        self._port = smtp_port
        self._user = smtp_user
        self._pass = smtp_pass
        self._to = to_addr

    def is_configured(self) -> bool:
        return bool(self._host and self._user and self._to)

    async def send(self, message: NotifyMessage) -> bool:
        if not self.is_configured():
            return False
        msg = MIMEText(message.body, "plain", "utf-8")
        msg["Subject"] = message.title
        msg["From"] = self._user  # type: ignore[assignment]  # is_configured guarantees non-None
        msg["To"] = self._to  # type: ignore[assignment]

        host = self._host
        port = self._port
        user = self._user
        password = self._pass

        def _send() -> None:
            with smtplib.SMTP(host, port, timeout=10) as s:  # type: ignore[arg-type]
                s.starttls()
                s.login(user, password or "")  # type: ignore[arg-type]
                s.send_message(msg)

        await asyncio.to_thread(_send)
        return True
