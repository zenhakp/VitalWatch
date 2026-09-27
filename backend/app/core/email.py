import logging
import time
from typing import Any, Dict

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)
MAILJET_API_URL = "https://api.mailjet.com/v3.1/send"


def send_otp_email(to_email: str, otp_code: str, recipient_name: str) -> bool:
    """
    Send OTP verification email via Mailjet.
    Works with any recipient email address — no domain restrictions.
    Returns True if sent successfully.
    """
    if not settings.MAILJET_API_KEY or not settings.MAILJET_SECRET_KEY:
        logger.error("Mailjet API credentials not configured in .env")
        return False

    if not settings.MAILJET_FROM_EMAIL:
        logger.error("MAILJET_FROM_EMAIL not configured in .env")
        return False

    # Split OTP into individual digits for styled display
    otp_digits = " ".join(list(otp_code))

    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>VitalWatch Verification</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background-color: #f1f5f9;
      padding: 40px 20px;
    }}
    .wrapper {{
      max-width: 520px;
      margin: 0 auto;
    }}
    .card {{
      background: white;
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);
    }}
    .header {{
      background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%);
      padding: 36px 32px;
      text-align: center;
    }}
    .header-icon {{
      font-size: 32px;
      margin-bottom: 12px;
    }}
    .header h1 {{
      color: white;
      font-size: 22px;
      font-weight: 700;
      letter-spacing: -0.3px;
    }}
    .header p {{
      color: #93c5fd;
      font-size: 14px;
      margin-top: 6px;
    }}
    .body {{
      padding: 36px 32px;
    }}
    .greeting {{
      font-size: 15px;
      color: #374151;
      margin-bottom: 12px;
    }}
    .description {{
      font-size: 14px;
      color: #6b7280;
      line-height: 1.6;
      margin-bottom: 28px;
    }}
    .otp-container {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 14px;
      padding: 28px;
      text-align: center;
      margin-bottom: 24px;
    }}
    .otp-label {{
      font-size: 12px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 1px;
      color: #94a3b8;
      margin-bottom: 16px;
    }}
    .otp-code {{
      font-size: 44px;
      font-weight: 800;
      letter-spacing: 8px;
      color: #1e3a8a;
      font-family: 'Courier New', Courier, monospace;
      margin-bottom: 12px;
      white-space: nowrap;
    }}
    .otp-expiry {{
      font-size: 13px;
      color: #94a3b8;
    }}
    .otp-expiry strong {{
      color: #ef4444;
    }}
    .divider {{
      height: 1px;
      background: #f1f5f9;
      margin: 24px 0;
    }}
    .security-box {{
      background: #fffbeb;
      border: 1px solid #fde68a;
      border-radius: 10px;
      padding: 16px;
      display: flex;
      gap: 12px;
      align-items: flex-start;
    }}
    .security-icon {{
      font-size: 18px;
      flex-shrink: 0;
    }}
    .security-text {{
      font-size: 13px;
      color: #78350f;
      line-height: 1.5;
    }}
    .security-text strong {{
      font-weight: 600;
    }}
    .footer {{
      background: #f8fafc;
      padding: 24px 32px;
      border-top: 1px solid #f1f5f9;
    }}
    .footer p {{
      font-size: 12px;
      color: #94a3b8;
      line-height: 1.6;
      text-align: center;
    }}
    .footer a {{
      color: #2563eb;
      text-decoration: none;
    }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="card">
      <div class="header">
        <h1>VitalWatch</h1>
        <p>AI-Powered Health Monitoring Platform</p>
      </div>

      <div class="body">
        <p class="greeting">Hello, <strong>{recipient_name}</strong></p>
        <p class="description">
          A sign-in attempt was made to your VitalWatch doctor account.
          Enter the verification code below to complete your login.
        </p>

        <div class="otp-container">
          <div class="otp-label">Your verification code</div>
          <div class="otp-code">{otp_digits}</div>
          <div class="otp-expiry">
            Expires in <strong>10 minutes</strong>
          </div>
        </div>

      <div class="footer">
        <p>
          This email was sent because a sign-in was attempted on
          <strong>VitalWatch</strong> for this account.<br>
          If you did not make this request, you can safely ignore this email.
        </p>
      </div>
    </div>

    <p style="text-align: center; font-size: 12px; color: #94a3b8; margin-top: 20px;">
      © 2026 VitalWatch · Secure Healthcare Monitoring
    </p>
  </div>
</body>
</html>
"""

    text_content = f"""
VitalWatch — Two-Factor Verification

Hello {recipient_name},

Your verification code is: {otp_code}

This code expires in 10 minutes.

SECURITY NOTICE: Never share this code with anyone. 
VitalWatch staff will never ask for your verification code.

If you did not attempt to sign in, contact your administrator immediately.

© 2026 VitalWatch
"""

    data = {
        "Messages": [
            {
                "From": {
                    "Email": settings.MAILJET_FROM_EMAIL,
                    "Name": settings.MAILJET_FROM_NAME,
                },
                "To": [
                    {
                        "Email": to_email,
                        "Name": recipient_name,
                    }
                ],
                "Subject": f"Your VitalWatch verification code — {otp_code}",
                "TextPart": text_content,
                "HTMLPart": html_content,
                "CustomID": f"vitalwatch-otp-{to_email}",
            }
        ]
    }

    try:
        result = mailjet.send.create(data=data)
        if result.status_code == 200:
            response_data = result.json()
            messages = response_data.get("Messages", [])
            if messages and messages[0].get("Status") == "success":
                logger.info(f"OTP email sent successfully to {to_email}")
                return True
            else:
                logger.error(f"Mailjet returned unexpected response: {response_data}")
                return False
        else:
            logger.error(f"Mailjet API error {result.status_code}: {result.json()}")
            return False
    except Exception as e:
        logger.error(f"Exception sending OTP email to {to_email}: {type(e).__name__}: {e}")
        return False