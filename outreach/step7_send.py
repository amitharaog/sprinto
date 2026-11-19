"""Step 7 - Send the email via Gmail.

TO: is hardcoded to your own inbox (MY_EMAIL). The prospect's address is
never used as a recipient - it's printed in the review notes under the email
so the Growth Lead can check everything before a real send. That's the
designed boundary of this build: the system researches and drafts, a human
decides what goes to a real prospect.

Transport: Gmail SMTP with an App Password (needs 2-Step Verification on the
Google account). Every email is also saved as a .eml file, sent or not.

Failure handling (decided up front, per tool):
  timeout / connection drop  -> transient: retry once, then skip this email (nothing downstream depends on it)
  authentication failure     -> permanent: stop sending for the whole run, keep saving .eml drafts
"""
from __future__ import annotations

import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from typing import Optional

from . import config


class AuthFailed(RuntimeError):
    pass


@dataclass
class SendResult:
    sent: bool
    to: str
    eml_path: str
    note: str
    message_id: Optional[str] = None


def build_message(subject: str, body: str, review_notes: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((config.SENDER_NAME, config.GMAIL_ADDRESS or "draft@localhost"))
    msg["To"] = config.MY_EMAIL or "you@example.com"        # HARDCODED: always your own inbox
    msg["Message-ID"] = make_msgid(domain="sprinto-outreach.local")
    content = body.rstrip() + "\n"
    if review_notes:
        content += "\n\n" + "-" * 60 + "\nREVIEW NOTES (pipeline output - not part of the email)\n" + review_notes
    msg.set_content(content)
    return msg


def send(msg: EmailMessage, eml_path: Path, dry_run: bool = False) -> SendResult:
    eml_path.parent.mkdir(parents=True, exist_ok=True)
    eml_path.write_bytes(bytes(msg))
    to = msg["To"]

    if dry_run:
        return SendResult(False, to, str(eml_path), "dry run: saved .eml, not sent")
    missing = [k for k, v in {"GMAIL_ADDRESS": config.GMAIL_ADDRESS, "GMAIL_APP_PASSWORD": config.GMAIL_APP_PASSWORD,
                              "MY_EMAIL": config.MY_EMAIL}.items() if not v]
    if missing:
        return SendResult(False, to, str(eml_path), f"not sent: set {', '.join(missing)} in .env")

    last_err = ""
    for attempt in range(2):
        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30) as smtp:
                smtp.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
                smtp.send_message(msg, to_addrs=[config.MY_EMAIL])
            return SendResult(True, to, str(eml_path), "sent via Gmail SMTP", msg["Message-ID"])
        except smtplib.SMTPAuthenticationError as e:
            raise AuthFailed(f"Gmail rejected the login ({e.smtp_code}). Use an App Password, not your normal "
                             "password: Google Account -> Security -> 2-Step Verification -> App passwords.") from e
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, TimeoutError, OSError) as e:
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(3)
    return SendResult(False, to, str(eml_path), f"skipped after retry: {last_err}")
