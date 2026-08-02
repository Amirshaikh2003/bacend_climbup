import sys
import os
sys.path.append(os.getcwd())

from app.api.routes.whatsapp import WebhookPayload, whatsapp_webhook
import asyncio

async def main():
    payload = WebhookPayload(
        message="Hellllo",
        sender_number="32925638746142",
        has_media=False
    )
    try:
        res = await whatsapp_webhook(payload)
        print("Success:", res)
    except Exception as e:
        print("Error:", e)
        import traceback
        traceback.print_exc()

asyncio.run(main())
