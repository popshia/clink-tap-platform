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
    <body style="font-family: 'Segoe UI', Arial, sans-serif; background: #f4f6f8; color: #1a1a1a; padding: 40px;">
      <div style="max-width: 560px; margin: 0 auto; background: #ffffff; border-radius: 8px; padding: 40px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); border-top: 4px solid #7E99A3;">
        <h1 style="color: #2c3e50; margin-top: 0; font-size: 22px; font-weight: 600;">Video Processing Complete</h1>
        <p style="line-height: 1.7; color: #444;">
          Your video has been successfully processed through all pipeline stages:
        </p>
        <table style="border-collapse: collapse; margin: 16px 0; font-size: 14px; color: #555;">
          <tr><td style="padding: 6px 12px 6px 0;">Stage 1 — Video Stabilization</td><td style="color: #5a8a6a; font-weight: 600;">Completed</td></tr>
          <tr><td style="padding: 6px 12px 6px 0;">Stage 2 — Object Detection</td><td style="color: #5a8a6a; font-weight: 600;">Completed</td></tr>
          <tr><td style="padding: 6px 12px 6px 0;">Stage 3 — Object Tracking</td><td style="color: #5a8a6a; font-weight: 600;">Completed</td></tr>
          <tr><td style="padding: 6px 12px 6px 0;">Stage 4 — CSV Postprocessing</td><td style="color: #5a8a6a; font-weight: 600;">Completed</td></tr>
        </table>
        <p style="line-height: 1.7; color: #444;">
          Please use the button below to download your processed output, which includes the stabilized video, tracking data (CSV), and background image.
        </p>
        <div style="text-align: center; margin: 32px 0;">
          <a href="{download_url}"
             style="background: #7E99A3; color: #ffffff; text-decoration: none; padding: 13px 32px; border-radius: 6px; font-weight: 600; font-size: 15px; display: inline-block; letter-spacing: 0.3px;">
            Download Results
          </a>
        </div>
        <p style="line-height: 1.7; color: #444;">
          Thank you for using TTGUI Video Processor. We appreciate your trust in our platform and hope the results meet your expectations.
        </p>
        <p style="font-size: 12px; color: #999; margin-top: 32px; border-top: 1px solid #e8e8e8; padding-top: 16px;">
          Job ID: {job_id}<br>
          This is an automated notification from TTGUI Video Processor. Please do not reply to this message.
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
        f"Your video (Job {job_id}) has been successfully processed.\n\n"
        f"Stages completed:\n"
        f"  Stage 1 - Video Stabilization\n"
        f"  Stage 2 - Object Detection\n"
        f"  Stage 3 - Object Tracking\n"
        f"  Stage 4 - CSV Postprocessing\n\n"
        f"Download your results here: {download_url}\n\n"
        f"Thank you for using TTGUI Video Processor. We appreciate your trust in our platform.\n\n"
        f"This is an automated notification. Please do not reply to this message."
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
