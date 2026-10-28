#!/usr/bin/env python3
"""
Demo Sales App — fires a signed 'lead.won' webhook to Opsyn.

Prerequisites:
  1. Create a webhook key via the Opsyn admin UI (Settings → Webhooks) or:
       curl -X POST http://localhost:8000/api/v1/webhooks/keys \
            -H "Authorization: Bearer <token>" \
            -H "Content-Type: application/json" \
            -d '{"app_name": "sales"}'
     Copy the returned secret_key.

  2. Run this script:
       python demos/sales_webhook_demo.py \
         --url    http://localhost:8000 \
         --tenant <tenant_uuid> \
         --secret <secret_key_from_step_1> \
         --dept   <department_uuid>   # optional
"""

import argparse
import hashlib
import hmac
import json
import secrets
import sys
import urllib.error
import urllib.request


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def send_event(base_url: str, tenant: str, secret: str, event: dict) -> None:
    body = json.dumps(event).encode()
    sig  = sign(secret, body)

    req = urllib.request.Request(
        f"{base_url}/api/v1/webhooks/receive",
        data=body,
        headers={
            "Content-Type":          "application/json",
            "X-Webhook-App":         "sales",
            "X-Webhook-Tenant":      tenant,
            "X-Webhook-Signature":   sig,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            print(f"  {resp.status} OK — {result.get('data', {}).get('message', '')}")
            print(f"  ticket: {result.get('data', {}).get('ticket_number', 'N/A')}")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        print(f"  {e.code} {e.reason} — {body_text}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo Sales webhook sender")
    parser.add_argument("--url",    default="http://localhost:8000", help="Opsyn base URL")
    parser.add_argument("--tenant", required=True, help="Tenant UUID")
    parser.add_argument("--secret", required=True, help="Webhook secret key")
    parser.add_argument("--dept",   default=None,  help="Department UUID (optional)")
    args = parser.parse_args()

    lead_id = f"LEAD-{secrets.token_hex(4).upper()}"

    event = {
        "event": "lead.won",
        "data": {
            "lead_id":         lead_id,
            "client_name":     "Acme Telecom Ltd",
            "project_name":    f"Acme Fiber Distribution — Lagos Island ({lead_id})",
            "project_type":    "external",
            "department_id":   args.dept,
            "estimated_value": 75_000,
            "notes":           "Demo event from sales_webhook_demo.py",
        },
    }

    print(f"\nSending lead.won event [{lead_id}]...")
    send_event(args.url, args.tenant, args.secret, event)
    print()


if __name__ == "__main__":
    main()
