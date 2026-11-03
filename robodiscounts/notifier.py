import os
from typing import Optional, Sequence

import requests

GRAPH_VERSION = "v21.0"


class NotificationError(RuntimeError):
    """A message could not be delivered (bad credentials, network, API refusal)."""


class ConfigError(RuntimeError):
    """WhatsApp credentials are missing."""


class WhatsAppNotifier:
    """Sends WhatsApp messages through Meta's WhatsApp Cloud API.

    Two modes:
    - Template (set WHATSAPP_TEMPLATE): works any time. The template body must have
      4 variables: {{1}} item name, {{2}} price, {{3}} reason, {{4}} url.
    - Free text (default): only delivered if you messaged the business number in
      the last 24 hours (Meta's customer-service window).
    """

    def __init__(self, token=None, phone_number_id=None, to=None, template=None, lang=None):
        token = token or os.environ.get("WHATSAPP_TOKEN")
        phone_number_id = phone_number_id or os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
        to = to or os.environ.get("WHATSAPP_TO")
        missing = [n for n, v in (("WHATSAPP_TOKEN", token),
                                  ("WHATSAPP_PHONE_NUMBER_ID", phone_number_id),
                                  ("WHATSAPP_TO", to)) if not v]
        if missing:
            raise ConfigError(
                "WhatsApp is not configured: set " + ", ".join(missing) + " (in .env or as secrets)"
            )
        self.token = token
        self.phone_number_id = phone_number_id
        self.to = to.lstrip("+")
        self.template = template or os.environ.get("WHATSAPP_TEMPLATE")
        self.lang = lang or os.environ.get("WHATSAPP_TEMPLATE_LANG", "en_US")
        # Optional 1-variable template for bot-health messages: "robodiscounts: {{1}}"
        self.status_template = os.environ.get("WHATSAPP_STATUS_TEMPLATE")

    def _post(self, payload: dict):
        try:
            r = requests.post(
                f"https://graph.facebook.com/{GRAPH_VERSION}/{self.phone_number_id}/messages",
                headers={"Authorization": f"Bearer {self.token}"},
                json={"messaging_product": "whatsapp", "to": self.to, **payload},
                timeout=30,
            )
        except requests.RequestException as e:
            raise NotificationError(f"WhatsApp request failed: {e}") from e
        if not r.ok:
            raise NotificationError(f"WhatsApp API error {r.status_code}: {r.text}")

    def send(self, body: str, params: Optional[Sequence[str]] = None):
        if self.template and params:
            self._post({
                "type": "template",
                "template": {
                    "name": self.template,
                    "language": {"code": self.lang},
                    "components": [{
                        "type": "body",
                        "parameters": [{"type": "text", "text": str(p)} for p in params],
                    }],
                },
            })
        else:
            self._post({"type": "text", "text": {"body": body}})


    def send_status(self, text: str):
        """Bot-health message (a product keeps failing, or recovered)."""
        if self.status_template:
            # Template variables may not contain newlines/tabs or long runs of spaces.
            one_line = " ".join(text.split())[:900]
            self._post({
                "type": "template",
                "template": {
                    "name": self.status_template,
                    "language": {"code": self.lang},
                    "components": [{
                        "type": "body",
                        "parameters": [{"type": "text", "text": one_line}],
                    }],
                },
            })
        else:
            self._post({"type": "text", "text": {"body": text}})


class UnconfiguredNotifier:
    """Stands in when WhatsApp credentials are missing: prices are still tracked,
    and every alert fails loudly (and is retried once credentials exist)."""

    def __init__(self, reason: str):
        self.reason = reason

    def send(self, body: str, params: Optional[Sequence[str]] = None):
        raise NotificationError(self.reason)

    def send_status(self, text: str):
        raise NotificationError(self.reason)


class ConsoleNotifier:
    """Dry-run notifier that prints instead of sending."""

    def send(self, body: str, params: Optional[Sequence[str]] = None):
        print(f"[WhatsApp dry-run]\n{body}\n")

    def send_status(self, text: str):
        print(f"[WhatsApp dry-run status]\n{text}\n")
