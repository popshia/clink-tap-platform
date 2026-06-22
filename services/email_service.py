import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from loguru import logger

import config


def _send(msg: MIMEMultipart, recipient: str, description: str) -> None:
    """Open a STARTTLS SMTP session, send msg to recipient, and log the outcome."""
    try:
        with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.sendmail(config.SMTP_USER, recipient, msg.as_string())
        logger.info(f"[EMAIL] Sent {description} to {recipient}")
    except Exception as exc:
        logger.error(f"[EMAIL] Failed to send {description} to {recipient}: {exc}")
        raise


def send_result_email(to_email: str, download_url: str, job_id: str):
    """Send an HTML email with the processed video download link via Gmail SMTP."""

    if not config.SMTP_USER or not config.SMTP_PASSWORD:
        logger.warning(
            f"[EMAIL] SMTP credentials not set. Skipping email to {to_email}"
        )
        logger.info(f"[EMAIL] Download link would be: {download_url}")
        return

    subject = f"Your Results Are Ready — Job {job_id}"

    html_body = f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:40px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #e0e0e0;">
        <tr>
          <td style="background:#4a6572;padding:28px 40px;">
            <span style="color:#ffffff;font-size:18px;font-weight:bold;letter-spacing:0.5px;">C-LINK TAP Platform</span>
          </td>
        </tr>
        <tr>
          <td style="padding:40px;">
            <h2 style="margin:0 0 16px;color:#1a1a1a;font-size:20px;font-weight:600;">Your results are ready for download.</h2>
            <p style="margin:0 0 32px;color:#555555;font-size:14px;line-height:1.8;">
              Your video has been processed successfully. The download package includes the stabilized video, vehicle tracking data (CSV), and background reference image.
            </p>
            <table cellpadding="0" cellspacing="0" style="margin:0 auto 32px;">
              <tr>
                <td style="background:#4a6572;border-radius:4px;">
                  <a href="{download_url}" style="display:inline-block;padding:12px 36px;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;letter-spacing:0.3px;">Download Results</a>
                </td>
              </tr>
            </table>
            <p style="margin:0 0 16px;color:#888888;font-size:12px;line-height:1.6;">
              If the button above does not work, copy and paste the following link into your browser:<br>
              <a href="{download_url}" style="color:#4a6572;word-break:break-all;">{download_url}</a>
            </p>
            <p style="margin:0 0 24px;padding:10px 14px;background:#fff8e1;border-left:3px solid #f0b429;color:#7a5c00;font-size:12px;line-height:1.6;">
              This download link expires in <strong>24 hours</strong>. Please download your results before then.
            </p>
            <p style="margin:0;color:#555555;font-size:14px;line-height:1.8;">
              Thank you for using C-LINK TAP Platform. We hope the results meet your expectations.
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 40px;border-top:1px solid #e8e8e8;background:#fafafa;">
            <p style="margin:0;color:#aaaaaa;font-size:11px;line-height:1.6;">
              Job ID: {job_id} &nbsp;|&nbsp; This is an automated notification. Please do not reply to this email.
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.SMTP_USER
    msg["To"] = to_email

    text_body = (
        f"Your results are ready for download.\n\n"
        f"Your video (Job {job_id}) has been processed successfully. The package includes the stabilized video, tracking data (CSV), and background image.\n\n"
        f"Download: {download_url}\n\n"
        f"IMPORTANT: This link expires in 24 hours. Please download your results before then.\n\n"
        f"Thank you for using C-LINK TAP Platform. We hope the results meet your expectations.\n\n"
        f"---\n"
        f"This is an automated notification. Please do not reply to this email."
    )
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    _send(msg, to_email, "result email")


def send_acknowledgment_email(to_email: str, job_id: str):
    """Send an HTML email confirming that the video upload was received and is being processed."""

    if not config.SMTP_USER or not config.SMTP_PASSWORD:
        print(
            f"[EMAIL] SMTP credentials not set. Skipping acknowledgment email to {to_email}"
        )
        return

    subject = f"We've Received Your Video — Job {job_id}"

    html_body = f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:40px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #e0e0e0;">
        <tr>
          <td style="background:#4a6572;padding:28px 40px;">
            <span style="color:#ffffff;font-size:18px;font-weight:bold;letter-spacing:0.5px;">C-LINK TAP Platform</span>
          </td>
        </tr>
        <tr>
          <td style="padding:40px;">
            <h2 style="margin:0 0 16px;color:#1a1a1a;font-size:20px;font-weight:600;">We've received your video.</h2>
            <p style="margin:0 0 16px;color:#555555;font-size:14px;line-height:1.8;">
              Your upload has been received and your video is now being analyzed. This process may take some time depending on the length and complexity of the footage.
            </p>
            <p style="margin:0 0 32px;color:#555555;font-size:14px;line-height:1.8;">
              Once processing is complete, we will send you a follow-up email with a link to download your results.
            </p>
            <p style="margin:0;color:#555555;font-size:14px;line-height:1.8;">
              Thank you for choosing C-LINK TAP Platform. We appreciate your trust in our platform.
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 40px;border-top:1px solid #e8e8e8;background:#fafafa;">
            <p style="margin:0;color:#aaaaaa;font-size:11px;line-height:1.6;">
              Job ID: {job_id} &nbsp;|&nbsp; This is an automated notification. Please do not reply to this email.
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text_body = (
        f"We've received your video.\n\n"
        f"Your upload (Job {job_id}) has been received and is now being analyzed. "
        f"Once processing is complete, we will send you a follow-up email with a link to download your results.\n\n"
        f"Thank you for choosing C-LINK TAP Platform. We appreciate your trust in our platform.\n\n"
        f"---\n"
        f"This is an automated notification. Please do not reply to this email."
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.SMTP_USER
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    _send(msg, to_email, "acknowledgment email")


def send_contact_email(name: str, email: str, phone: str, subject: str, message: str):
    """Forward a 'Contact Us' submission to the support inbox via Gmail SMTP."""

    recipient = config.CONTACT_RECIPIENT
    if not config.SMTP_USER or not config.SMTP_PASSWORD or not recipient:
        print(f"[CONTACT] SMTP not configured. Skipping contact email from {email}")
        print(f"[CONTACT] {name} <{email}> ({phone}) — {subject}: {message}")
        return

    mail_subject = f"[Contact Us] {subject}" if subject else "[Contact Us] New message"

    def esc(value: str) -> str:
        return (
            (value or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    html_body = f"""\
    <html>
    <body style="font-family: 'Segoe UI', Arial, sans-serif; color: #1a1a1a; padding: 24px;">
      <h2 style="color: #6b8fa3; margin-top: 0;">New Contact Us message</h2>
      <table style="border-collapse: collapse; font-size: 14px;">
        <tr><td style="padding: 4px 12px 4px 0; color: #555;"><b>Name</b></td><td>{esc(name)}</td></tr>
        <tr><td style="padding: 4px 12px 4px 0; color: #555;"><b>Email</b></td><td>{esc(email)}</td></tr>
        <tr><td style="padding: 4px 12px 4px 0; color: #555;"><b>Phone</b></td><td>{esc(phone)}</td></tr>
        <tr><td style="padding: 4px 12px 4px 0; color: #555;"><b>Subject</b></td><td>{esc(subject)}</td></tr>
      </table>
      <p style="margin-top: 16px; line-height: 1.6; white-space: pre-wrap;">{esc(message)}</p>
    </body>
    </html>
    """

    text_body = (
        f"New Contact Us message\n\n"
        f"Name: {name}\n"
        f"Email: {email}\n"
        f"Phone: {phone}\n"
        f"Subject: {subject}\n\n"
        f"{message}\n"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = mail_subject
    msg["From"] = config.SMTP_USER
    msg["To"] = recipient
    if email:
        msg["Reply-To"] = email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    _send(msg, recipient, f"contact message from {email}")
