import os

import requests


class WhatsAppNotifier:
    """Sends WhatsApp messages through Twilio's REST API."""

    def __init__(self, sid=None, token=None, from_=None, to=None):
        self.sid = sid or os.environ["TWILIO_ACCOUNT_SID"]
        self.token = token or os.environ["TWILIO_AUTH_TOKEN"]
        self.from_ = from_ or os.environ["TWILIO_WHATSAPP_FROM"]
        self.to = to or os.environ["WHATSAPP_TO"]

    def send(self, body: str):
        r = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json",
            auth=(self.sid, self.token),
            data={"From": self.from_, "To": self.to, "Body": body},
            timeout=30,
        )
        r.raise_for_status()


class ConsoleNotifier:
    """Dry-run notifier that prints instead of sending."""

    def send(self, body: str):
        print(f"[WhatsApp dry-run]\n{body}\n")
