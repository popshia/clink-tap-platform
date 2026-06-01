import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config


def send_result_email(to_email: str, download_url: str, job_id: str):
    """Send an HTML email with the processed video download link via Gmail SMTP."""

    if not config.SMTP_USER or not config.SMTP_PASSWORD:
        print(f"[EMAIL] SMTP credentials not set. Skipping email to {to_email}")
        print(f"[EMAIL] Download link would be: {download_url}")
        return

    subject = f"Your processed video is ready! (Job {job_id})"

    html_body = f"""\
    <html>
    <body style="font-family: 'Segoe UI', Arial, sans-serif; background: #0f0f23; color: #e0e0e0; padding: 40px;">
      <div style="max-width: 560px; margin: 0 auto; background: linear-gradient(135deg, #1a1a3e, #16213e); border-radius: 16px; padding: 40px; box-shadow: 0 8px 32px rgba(0,0,0,0.4);">
        <h1 style="color: #818cf8; margin-top: 0; font-size: 24px;">🎬 Video Processing Complete</h1>
        <p style="line-height: 1.7; color: #c0c0d0;">
          Great news! Your video has been processed through all three stages:
        </p>
        <ul style="line-height: 2; color: #a0a0c0;">
          <li>✅ Video Stabilization</li>
          <li>✅ Object Tracking</li>
          <li>✅ CSV Postprocessing</li>
        </ul>
        <p style="line-height: 1.7; color: #c0c0d0;">
          Click the button below to download your processed video:
        </p>
        <div style="text-align: center; margin: 32px 0;">
          <a href="{download_url}"
             style="background: linear-gradient(135deg, #6366f1, #8b5cf6); color: white; text-decoration: none; padding: 14px 32px; border-radius: 10px; font-weight: 600; font-size: 16px; display: inline-block;">
            ⬇️ Download Video
          </a>
        </div>
        <p style="font-size: 13px; color: #666; margin-top: 32px; border-top: 1px solid #2a2a4a; padding-top: 16px;">
          Job ID: {job_id}<br>
          This is an automated message from TTGUI Video Processor.
        </p>
      </div>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.SMTP_USER
    msg["To"] = to_email

    # Plain-text fallback
    text_body = (
        f"Your video (Job {job_id}) has been processed!\n\n"
        f"Download it here: {download_url}\n\n"
        f"Stages completed: Stabilization, Object Detection, Object Tracking."
    )
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.sendmail(config.SMTP_USER, to_email, msg.as_string())

    print(f"[EMAIL] Sent result email to {to_email}")


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

    with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.sendmail(config.SMTP_USER, recipient, msg.as_string())

    print(f"[CONTACT] Forwarded contact message from {email} to {recipient}")
