"""Beispiel-Plugin: Tasten per Webhook.

Kopieren nach ``/config/switchboard/plugins/webhook_button.py`` und im
Switchboard-Panel unter „Plugins & Definitionen“ auf „Neu laden“ klicken.

Damit lassen sich z. B. Shelly-Gen1-„Actions“-URLs, iOS-Kurzbefehle, NFC-Tags
oder ESP-Bastelprojekte als „Schalter“ einbinden::

    POST http://homeassistant:8123/api/webhook/<webhook_id>?button=1&action=single

Der Plugin-Teil reicht nur Query-Parameter und JSON-Body als Nachricht weiter.
Welche Kombination welche Taste ist, steht in der Definition unten (``match``).
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.switchboard.api import SourceContext, SourcePlugin

_LOGGER = logging.getLogger(__name__)


class WebhookPlugin(SourcePlugin):
    key = "webhook"
    name = "Webhook"
    description = "Nimmt Tastendrücke als HTTP-Aufruf auf /api/webhook/<id> entgegen (nur lokales Netz)."
    default_inputs = [
        {
            "key": "webhook_id",
            "name": "Webhook-ID",
            "description": "Frei wählbar, möglichst schwer zu erraten",
            "required": True,
            "selector": {"text": {}},
            "multiple": False,
        }
    ]

    async def async_setup(self) -> bool:
        return await async_setup_component(self.hass, "webhook", {})

    async def async_attach(self, ctx: SourceContext) -> CALLBACK_TYPE:
        from homeassistant.components import webhook  # noqa: PLC0415

        webhook_id = ctx.inputs["webhook_id"]

        async def _handle(hass: HomeAssistant, wh_id: str, request: web.Request) -> web.Response:
            data: dict[str, Any] = dict(request.query)
            if request.can_read_body:
                try:
                    body = await request.json()
                except ValueError:
                    body = {"body": await request.text()}
                if isinstance(body, dict):
                    data.update(body)
            ctx.emit(data)
            return web.Response(status=200, text="ok")

        webhook.async_register(
            self.hass,
            "switchboard",
            f"Switchboard: {ctx.switch_name}",
            webhook_id,
            _handle,
            local_only=True,
            allowed_methods=["GET", "POST"],
        )
        return lambda: webhook.async_unregister(self.hass, webhook_id)


PLUGINS = [WebhookPlugin]

# Eine Definition kann direkt im Plugin mitkommen (alternativ als YAML-Datei).
DEFINITIONS = [
    {
        "id": "webhook_3_buttons",
        "name": "Webhook-Taster (3 Tasten)",
        "manufacturer": "Eigenbau",
        "integration": "Webhook",
        "description": "?button=1..3&action=single|double|long",
        "source": "webhook",
        "buttons": [
            {
                "id": f"button_{n}",
                "name": f"Taste {n}",
                "match": {"button": str(n)},
                "actions": [
                    {"id": "single", "name": "Kurz", "match": {"action": "single"}},
                    {"id": "double", "name": "Doppelt", "match": {"action": "double"}},
                    {"id": "long", "name": "Lang", "match": {"action": "long"}},
                ],
            }
            for n in (1, 2, 3)
        ],
    }
]
