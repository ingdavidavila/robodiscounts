import os
from typing import Optional, Sequence

import requests

GRAPH_VERSION = "v21.0"


class WhatsAppNotifier:
    """Sends WhatsApp messages through Meta's WhatsApp Cloud API.

    Two modes:
    - Template (set WHATSAPP_TEMPLATE): works any time. The template body must have
      4 variables: {{1}} item name, {{2}} price, {{3}} reason, {{4}} url.
    - Free text (default): only delivered if you messaged the business number in
      the last 24 hours (Meta's customer-service window).
    """

    def __init__(self, token=None, phone_number_id=None, to=None, template=None, lang=None):
        self.token = token or os.environ["WHATSAPP_TOKEN"]
        self.phone_number_id = phone_number_id or os.environ["WHATSAPP_PHONE_NUMBER_ID"]
        self.to = (to or os.environ["WHATSAPP_TO"]).lstrip("+")
        self.template = template or os.environ.get("WHATSAPP_TEMPLATE")
        self.lang = lang or os.environ.get("WHATSAPP_TEMPLATE_LANG", "en_US")
        # Optional 1-variable template for bot-health messages: "robodiscounts: {{1}}"
        self.status_template = os.environ.get("WHATSAPP_STATUS_TEMPLATE")

    def _post(self, payload: dict):
        r = requests.post(
            f"https://graph.facebook.com/{GRAPH_VERSION}/{self.phone_number_id}/messages",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"messaging_product": "whatsapp", "to": self.to, **payload},
            timeout=30,
        )
        if not r.ok:
            raise RuntimeError(f"WhatsApp API error {r.status_code}: {r.text}")

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


class ConsoleNotifier:
    """Dry-run notifier that prints instead of sending."""

    def send(self, body: str, params: Optional[Sequence[str]] = None):
        print(f"[WhatsApp dry-run]\n{body}\n")

    def send_status(self, text: str):
        print(f"[WhatsApp dry-run status]\n{text}\n")
