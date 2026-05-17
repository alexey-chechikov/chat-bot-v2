"""TradingView webhook receiver — Pine alert → bot7 ingest.

Exposes HTTP POST endpoint /tv/<secret_token>/alert on port 8770.
Pine scripts on TV side fire alerts with JSON body → bot persists to
state/tv_alerts.jsonl + optionally triggers bot_brain rule.

See docs/TV_WEBHOOK_SETUP_2026-05-17.md for ngrok/cloudflared tunnel setup +
Pine script templates.
"""
from .server import tv_webhook_loop  # noqa: F401
