"""PDF report generation (WeasyPrint) and email delivery for GBP audits."""

from __future__ import annotations

from typing import Any

from shared.config.settings import settings
from shared.logger import get_logger
from shared.storage.client import storage

from .db import GraderDB
from .email import GraderMailer

logger = get_logger(__name__)

_SCORE_COLOR = {
    "great": "#22c55e",   # >= 75
    "ok": "#f59e0b",      # >= 50
    "poor": "#ef4444",    # < 50
}


def _score_color(score: int) -> str:
    if score >= 75:
        return _SCORE_COLOR["great"]
    if score >= 50:
        return _SCORE_COLOR["ok"]
    return _SCORE_COLOR["poor"]


def _category_label(key: str) -> str:
    return {
        "completeness": "Profile Completeness",
        "photos": "Photo Score",
        "reviews": "Review Score",
        "posts": "Post Activity",
        "qa": "Q&A Presence",
        "services": "Services / Products",
        "keywords": "Keyword Optimization",
        "citations": "Citation Consistency",
    }.get(key, key.title())


def _score_bar(score: int, max_score: int) -> str:
    pct = int(score / max_score * 100) if max_score else 0
    color = _score_color(int(score / max_score * 100) if max_score else 0)
    return (
        f'<div style="background:#e5e7eb;border-radius:4px;height:10px;margin-top:4px">'
        f'<div style="background:{color};width:{pct}%;height:10px;border-radius:4px"></div></div>'
    )


class ReportGenerator:
    _WEIGHTS = {
        "completeness": 25, "photos": 15, "reviews": 25, "posts": 10,
        "qa": 5, "services": 5, "keywords": 10, "citations": 5,
    }

    def __init__(self, db: GraderDB, mailer: GraderMailer) -> None:
        self._db = db
        self._mailer = mailer

    def deliver(
        self,
        audit_id: str,
        audit_data: dict[str, Any],
        benchmarks: list[dict[str, Any]],
        lead_id: str,
    ) -> dict[str, Any]:
        business_name = audit_data.get("business_name", "Your Business")
        score = audit_data["overall_score"]
        contact_email = audit_data["contact_email"]
        contact_name = audit_data.get("contact_name") or "there"
        category_scores = audit_data["category_scores"]
        recommendations = audit_data["recommendations"]

        html_full = self._render_pdf_html(
            business_name, score, category_scores, recommendations, benchmarks, contact_name
        )
        html_email = self._render_email_html(
            business_name, score, category_scores, recommendations, benchmarks,
            contact_name, lead_id
        )

        pdf_bytes = self._to_pdf(html_full)
        if not pdf_bytes:
            raise RuntimeError(f"PDF generation failed for audit {audit_id}")
        report_key = f"reports/{audit_id}/GBP_Audit_{business_name.replace(' ', '_')}.pdf"
        report_url = storage.upload_bytes(pdf_bytes, report_key, "application/pdf")
        self._db.set_report_url(audit_id, report_url)

        self._mailer.send_report(
            to_email=contact_email,
            to_name=contact_name,
            business_name=business_name,
            score=score,
            lead_id=lead_id,
            pdf_bytes=pdf_bytes,
            html_preview=html_email,
        )

        logger.info("report_delivered", audit_id=audit_id, score=score, email=contact_email)
        return {"report_url": report_url, "score": score}

    # ------------------------------------------------------------------
    # HTML rendering
    # ------------------------------------------------------------------

    def _render_pdf_html(
        self,
        business_name: str,
        score: int,
        category_scores: dict[str, int],
        recommendations: list[dict[str, Any]],
        benchmarks: list[dict[str, Any]],
        contact_name: str,
    ) -> str:
        color = _score_color(score)
        rows = ""
        for key, max_pts in self._WEIGHTS.items():
            pts = category_scores.get(key, 0)
            rows += (
                f"<tr>"
                f"<td style='padding:8px;border-bottom:1px solid #e5e7eb'>{_category_label(key)}</td>"
                f"<td style='padding:8px;border-bottom:1px solid #e5e7eb;text-align:right'>{pts}/{max_pts}</td>"
                f"</tr>"
            )

        rec_items = "".join(
            f"<li style='margin-bottom:8px'><strong>{r['category'].title()}:</strong> {r['action']}</li>"
            for r in recommendations[:3]
        )

        bench_html = ""
        if benchmarks:
            avg_score = round(sum(b["competitor_score"] for b in benchmarks) / len(benchmarks))
            bench_html = f"""
            <h2 style='color:#1f2937;margin-top:32px'>Competitor Comparison</h2>
            <p>Competitors in your area average <strong>{avg_score}/100</strong>. You scored <strong>{score}/100</strong>.</p>
            <table style='width:100%;border-collapse:collapse;margin-top:12px'>
              {"".join(f"<tr><td style='padding:6px;border-bottom:1px solid #e5e7eb'>{b['competitor_name']}</td><td style='padding:6px;border-bottom:1px solid #e5e7eb;text-align:right'>{b['competitor_score']}/100</td></tr>" for b in benchmarks)}
            </table>
            """

        trial_url = settings.LOCALOUTRANK_TRIAL_URL
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
  body {{font-family:Arial,sans-serif;margin:40px;color:#1f2937;font-size:14px}}
  h1 {{color:#111827}} h2 {{color:#374151}}
  .badge {{display:inline-block;background:{color};color:#fff;font-size:48px;font-weight:bold;
           padding:24px 36px;border-radius:16px;margin:16px 0}}
</style>
</head><body>
<h1>Google Business Profile Audit</h1>
<h2>{business_name}</h2>
<p>Prepared for: {contact_name}</p>
<div class="badge">{score}/100</div>
<h2 style="margin-top:32px">Score Breakdown</h2>
<table style="width:100%;border-collapse:collapse">
  <thead><tr>
    <th style="text-align:left;padding:8px;border-bottom:2px solid #e5e7eb">Category</th>
    <th style="text-align:right;padding:8px;border-bottom:2px solid #e5e7eb">Score</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table>
<h2 style="margin-top:32px">Top 3 Quick Wins</h2>
<ol style="padding-left:20px">{rec_items}</ol>
{bench_html}
<div style="margin-top:40px;padding:24px;background:#f0fdf4;border-radius:12px;text-align:center">
  <h2 style="color:#15803d">Want These Fixed Automatically?</h2>
  <p>LocalOutRank.AI monitors and optimizes your GBP for you — 24/7.</p>
  <a href="{trial_url}" style="display:inline-block;background:#16a34a;color:#fff;padding:14px 28px;
     border-radius:8px;text-decoration:none;font-size:16px;font-weight:bold">
    Start Your Free Trial →
  </a>
</div>
</body></html>"""

    def _render_email_html(
        self,
        business_name: str,
        score: int,
        category_scores: dict[str, int],
        recommendations: list[dict[str, Any]],
        benchmarks: list[dict[str, Any]],
        contact_name: str,
        lead_id: str,
    ) -> str:
        color = _score_color(score)
        category_rows = "".join(
            f"<tr><td style='padding:6px 0'>{_category_label(k)}</td>"
            f"<td style='padding:6px 0;text-align:right;font-weight:bold'>{v}/{self._WEIGHTS.get(k, 0)}</td></tr>"
            for k, v in category_scores.items()
        )

        top_rec = recommendations[0]["action"] if recommendations else "Review your full report for improvements."
        bench_line = ""
        if benchmarks:
            avg = round(sum(b["competitor_score"] for b in benchmarks) / len(benchmarks))
            bench_line = f"<p style='color:#6b7280;font-size:13px'>Competitors in your area avg <strong>{avg}/100</strong>.</p>"

        click_url = self._click_url(lead_id, settings.LOCALOUTRANK_TRIAL_URL, pricing=True)
        return f"""<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px">
  <h2 style="color:#111827">{business_name} — Google Score: <span style="color:{color}">{score}/100</span></h2>
  <p>Hi {contact_name},</p>
  <p>We just audited <strong>{business_name}'s</strong> Google Business Profile. Here's what we found:</p>
  <table style="width:100%;border-collapse:collapse;margin:16px 0">{category_rows}</table>
  {bench_line}
  <p><strong>Your #1 Quick Win:</strong> {top_rec}</p>
  <p>The full PDF audit report is attached to this email.</p>
  <a href="{click_url}" style="display:inline-block;background:#16a34a;color:#fff;
     padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;margin-top:16px">
    Fix These Issues with LocalOutRank.AI →
  </a>
  <p style="color:#9ca3af;font-size:12px;margin-top:32px">
    LocalRankGrader.com — Free GBP Audit Tool
  </p>
</div>"""

    def _click_url(self, lead_id: str, destination: str, pricing: bool = False) -> str:
        from urllib.parse import quote_plus
        base = settings.GRADER_TRACKER_URL.rstrip("/")
        encoded = quote_plus(destination)
        p = "&pricing=1" if pricing else ""
        return f"{base}/hooks/grader/click/{lead_id}?to={encoded}{p}"

    def _to_pdf(self, html: str) -> bytes:
        try:
            from weasyprint import HTML
            return HTML(string=html).write_pdf()  # type: ignore[no-any-return]
        except Exception as exc:
            logger.error("weasyprint_failed", error=str(exc))
            return b""
