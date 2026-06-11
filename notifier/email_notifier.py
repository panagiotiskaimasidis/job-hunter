"""Send a summary email when new job matches are found."""

import logging
import smtplib
import ssl
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config

logger = logging.getLogger(__name__)


def send_match_digest(matches: list[dict]) -> None:
    """Send an HTML digest email of new job matches. No-op if email is not configured."""
    if not config.EMAIL_FROM or not config.EMAIL_TO or not config.EMAIL_SMTP_PASSWORD:
        logger.info("[email] Not configured — skipping notification.")
        return

    count = len(matches)
    subject = f"Job Hunter: {count} new match{'es' if count != 1 else ''} — {date.today()}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_FROM
    msg["To"] = config.EMAIL_TO
    msg.attach(MIMEText(_build_text(matches), "plain"))
    msg.attach(MIMEText(_build_html(matches), "html"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(config.EMAIL_SMTP_HOST, config.EMAIL_SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.login(config.EMAIL_FROM, config.EMAIL_SMTP_PASSWORD)
            smtp.sendmail(config.EMAIL_FROM, config.EMAIL_TO, msg.as_string())
        logger.info("[email] Digest sent → %s (%d match(es))", config.EMAIL_TO, count)
    except Exception as exc:
        logger.error("[email] Failed to send digest: %s", exc)


def _build_text(matches: list[dict]) -> str:
    lines = [f"Job Hunter found {len(matches)} new match(es) on {date.today()}:\n"]
    for m in matches:
        link = m.get("notion_url") or m.get("url", "")
        lines.append(
            f"  [{m['score']}/10] {m['title']} @ {m['company']} ({m.get('location', '')})\n"
            f"  {link}\n"
        )
    lines.append("\nOpen your Notion dashboard to review and set 'Generate Docs → Yes' for roles you want to apply to.")
    return "\n".join(lines)


def _build_html(matches: list[dict]) -> str:
    rows = []
    for m in matches:
        link_url = m.get("notion_url") or m.get("url", "#")
        verdict_color = {"STRONG_MATCH": "#16a34a", "GOOD_MATCH": "#2563eb"}.get(
            m.get("verdict", ""), "#6b7280"
        )
        rows.append(
            f"<tr style='border-bottom:1px solid #e2e8f0'>"
            f"<td style='padding:10px 12px;font-weight:700;color:#2563eb;font-size:15px'>{m['score']}/10</td>"
            f"<td style='padding:10px 12px'><a href='{link_url}' style='color:#1d4ed8;text-decoration:none;font-weight:500'>{m['title']}</a></td>"
            f"<td style='padding:10px 12px'>{m['company']}</td>"
            f"<td style='padding:10px 12px;color:#6b7280'>{m.get('location', '')}</td>"
            f"<td style='padding:10px 12px;color:{verdict_color};font-size:13px'>{m.get('verdict', '')}</td>"
            f"</tr>"
        )
    table_rows = "\n".join(rows)
    count = len(matches)
    return f"""<!DOCTYPE html>
<html>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:700px;margin:0 auto;padding:24px;color:#111827;background:#f8fafc">
  <div style="background:#fff;border-radius:12px;padding:32px;box-shadow:0 1px 3px rgba(0,0,0,.08)">
    <h2 style="margin:0 0 4px;color:#1d4ed8">&#127919; Job Hunter</h2>
    <p style="margin:0 0 24px;color:#6b7280;font-size:14px">{date.today()} &mdash; {count} new match{'es' if count != 1 else ''} found</p>
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr style="background:#f1f5f9;text-align:left">
          <th style="padding:8px 12px;font-size:13px;color:#374151">Score</th>
          <th style="padding:8px 12px;font-size:13px;color:#374151">Role</th>
          <th style="padding:8px 12px;font-size:13px;color:#374151">Company</th>
          <th style="padding:8px 12px;font-size:13px;color:#374151">Location</th>
          <th style="padding:8px 12px;font-size:13px;color:#374151">Verdict</th>
        </tr>
      </thead>
      <tbody>
{table_rows}
      </tbody>
    </table>
    <p style="margin-top:28px;padding:16px;background:#eff6ff;border-radius:8px;color:#1e40af;font-size:14px">
      &#128161; Open your <a href="https://notion.so" style="color:#1d4ed8;font-weight:600">Notion dashboard</a>
      to review these matches. Set <strong>Generate Docs &rarr; Yes</strong> on any role you want to apply to
      and the CV &amp; cover letter will be generated automatically.
    </p>
  </div>
</body>
</html>"""
