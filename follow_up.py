#!/usr/bin/env python3
"""
Follow-up automation with error alerts.

Walks a prepared contact list, sends the follow-up step that is due today,
remembers what has already gone out, retries a failed send, and - if it still
can't deliver - writes an alert instead of failing silently.

The point of the alerting is simple: a follow-up that quietly never went out
costs you the customer, and you only find out weeks later.

Usage
-----
    python follow_up.py                       # dry run: writes emails to outbox/
    python follow_up.py --simulate-failure jane@acme.example
    python follow_up.py --smtp                # real send, credentials from env

Environment for a real send:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_FROM
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import smtplib
import sys
import time
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

SEQUENCE = [
    {
        "step": 1,
        "after_days": 0,
        "subject": "Quick question about {company}",
        "body": (
            "Hi {first},\n\n"
            "I noticed {company} still handles {topic} by hand. I build small automations "
            "that take that off the team's plate - usually in under a week.\n\n"
            "Worth a short call, or shall I send over a two-minute example instead?\n\n"
            "Best,\n{sender}"
        ),
    },
    {
        "step": 2,
        "after_days": 3,
        "subject": "Re: Quick question about {company}",
        "body": (
            "Hi {first},\n\n"
            "Following up on my note from earlier this week. If the timing is wrong, "
            "just say so and I'll close the loop - no hard feelings.\n\n"
            "Best,\n{sender}"
        ),
    },
    {
        "step": 3,
        "after_days": 7,
        "subject": "Closing the loop, {first}",
        "body": (
            "Hi {first},\n\n"
            "I'll stop here so I'm not cluttering your inbox. If {topic} comes back onto "
            "your list this quarter, reply to this note and I'll pick it straight up.\n\n"
            "Best,\n{sender}"
        ),
    },
]
SKIP_STAGES = {"customer", "opted_out", "closed"}


def build_logger(path: Path) -> logging.Logger:
    logger = logging.getLogger("followup")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    logger.addHandler(stream)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


class DryRunSender:
    """Default sender: no SMTP, no credentials, writes the message to outbox/."""

    name = "dry-run"

    def __init__(self, outbox: Path) -> None:
        self.outbox = outbox
        self.outbox.mkdir(parents=True, exist_ok=True)

    def send(self, contact: dict, subject: str, body: str) -> None:
        path = self.outbox / f"{contact['contact_id']}_step{contact['_step']}.txt"
        path.write_text(f"To: {contact['email']}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")


class SmtpSender:
    """Real sender. Credentials stay in environment variables, never in the code."""

    name = "smtp"

    def __init__(self) -> None:
        self.host = os.environ["SMTP_HOST"]
        self.port = int(os.environ.get("SMTP_PORT", "587"))
        self.user = os.environ["SMTP_USER"]
        self.password = os.environ["SMTP_PASSWORD"]
        self.sender = os.environ.get("MAIL_FROM", self.user)

    def send(self, contact: dict, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = contact["email"]
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=30) as server:
            server.starttls()
            server.login(self.user, self.password)
            server.send_message(message)


class FlakySender:
    """Wraps another sender and fails the first attempts for one address, on purpose,
    so the retry-and-alert behaviour can be demonstrated end to end."""

    def __init__(self, inner, failing_email: str, failures: int = 2) -> None:
        self.inner = inner
        self.failing_email = failing_email
        self.remaining = failures
        self.name = f"{inner.name}+fault-injection"

    def send(self, contact: dict, subject: str, body: str) -> None:
        if contact["email"] == self.failing_email and self.remaining > 0:
            self.remaining -= 1
            raise ConnectionError("simulated 554 delivery failure")
        self.inner.send(contact, subject, body)


def due_step(contact: dict, sent: list[dict], today: date) -> dict | None:
    start = datetime.strptime(contact["last_touch"], "%Y-%m-%d").date()
    steps_done = {entry["step"] for entry in sent}
    last_sent = max((datetime.strptime(e["at"], "%Y-%m-%d").date() for e in sent), default=None)
    for step in SEQUENCE:
        if step["step"] in steps_done:
            continue
        baseline = last_sent or start
        if today >= baseline + timedelta(days=step["after_days"]):
            return step
        return None
    return None


def fill(template: str, contact: dict, sender_name: str) -> str:
    first = contact["name"].split()[0]
    return template.format(
        first=first,
        company=contact["company"],
        topic=contact.get("topic") or "reporting",
        sender=sender_name,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Send the follow-up step that is due today.")
    parser.add_argument("--contacts", default="sample_data/contacts.csv")
    parser.add_argument("--state", default="state/state.json")
    parser.add_argument("--outbox", default="outbox")
    parser.add_argument("--log", default="output/run.log")
    parser.add_argument("--alerts", default="output/alerts.log")
    parser.add_argument("--sender-name", default="Huihu")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--smtp", action="store_true", help="send for real (needs SMTP_* env vars)")
    parser.add_argument("--simulate-failure", default="",
                        help="demo the alerting: fail this address twice before it goes through")
    args = parser.parse_args()

    logger = build_logger(Path(args.log))
    state_path = Path(args.state)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}

    sender = SmtpSender() if args.smtp else DryRunSender(Path(args.outbox))
    if args.simulate_failure:
        sender = FlakySender(sender, args.simulate_failure)
    logger.info("run started | sender=%s | contacts=%s", sender.name, args.contacts)

    with open(args.contacts, newline="", encoding="utf-8") as handle:
        contacts = list(csv.DictReader(handle))

    today = date.today()
    sent_count = 0
    alerts: list[dict] = []

    for contact in contacts:
        record = state.setdefault(contact["contact_id"], {"sent": [], "failed": []})
        if contact.get("opted_out", "").strip().lower() in {"1", "yes", "true"}:
            continue
        if contact.get("stage", "").strip().lower() in SKIP_STAGES:
            continue

        step = due_step(contact, record["sent"], today)
        if step is None:
            continue

        contact["_step"] = step["step"]
        subject = fill(step["subject"], contact, args.sender_name)
        body = fill(step["body"], contact, args.sender_name)

        for attempt in range(1, args.retries + 1):
            try:
                sender.send(contact, subject, body)
                record["sent"].append({"step": step["step"], "at": today.isoformat(),
                                       "subject": subject})
                sent_count += 1
                logger.info("sent step %s to %s <%s>", step["step"], contact["name"], contact["email"])
                break
            except Exception as exc:                     # noqa: BLE001 - any failure must raise an alert
                if attempt < args.retries:
                    logger.warning("attempt %s/%s failed for %s - retrying (%s)",
                                   attempt, args.retries, contact["email"], exc)
                    time.sleep(min(2 ** attempt, 8))
                    continue
                logger.error("ALERT send failed permanently for %s <%s>: %s",
                             contact["name"], contact["email"], exc)
                alerts.append({
                    "contact_id": contact["contact_id"],
                    "email": contact["email"],
                    "step": step["step"],
                    "error": str(exc),
                    "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                # Keep one entry per contact + step: the state file describes the current
                # permanent failures, not their history (the history is in the alert log and
                # the run log). Without this, every rehearsal of the failure path piles up
                # duplicate rows for the same contact and the file stops being readable.
                record["failed"] = [
                    entry
                    for entry in record["failed"]
                    if not (
                        entry.get("contact_id") == alerts[-1]["contact_id"]
                        and entry.get("step") == alerts[-1]["step"]
                    )
                ] + [alerts[-1]]

    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    if alerts:
        alert_path = Path(args.alerts)
        alert_path.parent.mkdir(parents=True, exist_ok=True)
        with alert_path.open("a", encoding="utf-8") as handle:
            for alert in alerts:
                handle.write(json.dumps(alert) + "\n")

    logger.info("finished | sent=%s | alerts=%s | state=%s",
                sent_count, len(alerts), state_path.as_posix())
    return 2 if alerts else 0


if __name__ == "__main__":
    raise SystemExit(main())
，，你看
