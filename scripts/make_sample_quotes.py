"""Generate 9 fake vendor quote PDFs plus expected-extraction JSON.

Three categories (IT support, office cleaning, catering), three vendors each.
Every quote hides deliberate traps (hidden setup fee, auto-renewal, price
escalator, missing item, mixed billing units). The same text that is rendered
into the PDF is stored as the `source_snippet` in the expected JSON, and the
script verifies each snippet really appears in the PDF text (via pdfplumber).

Usage:
    python scripts/make_sample_quotes.py [--out tests/fixtures]

Requires reportlab (see requirements-dev.txt).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from xml.sax.saxutils import escape

import pdfplumber
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

TERM_KEYS = [
    "contract_months",
    "auto_renewal",
    "renewal_notice_days",
    "price_escalator_percent",
    "late_fee_percent",
    "payment_terms_days",
]


def money(x: float) -> str:
    return f"${x:,.2f}"


def item(description, quantity, unit_price, billing_unit, multiplier, text):
    """A priced line item.

    annual cost = quantity * unit_price * multiplier. For per-occurrence
    billing (visits, lunches) the quantity is already the annual count and the
    multiplier is 1.
    """
    return {
        "description": description,
        "quantity": quantity,
        "unit_price": unit_price,
        "billing_unit": billing_unit,
        "annual_multiplier": multiplier,
        "source_snippet": text,
    }


def fee(name, amount, recurring, multiplier, text, hidden=False, billing_unit=None, quantity=None):
    return {
        "name": name,
        "amount": amount,
        "recurring": recurring,
        "annual_multiplier": multiplier,
        "hidden_in_fine_print": hidden,
        "billing_unit": billing_unit,
        "quantity": quantity,
        "source_snippet": text,
    }


def term(value, text):
    return {"value": value, "source_snippet": text}


QUOTES = [
    # ------------------------------------------------------------------ IT
    {
        "file": "it_netsure.pdf",
        "category": "it_support",
        "vendor": "NetSure IT Services",
        "date": "October 6, 2026",
        "scope": "Managed IT support for a 25-person office, 12 month engagement.",
        "items": [
            item("Managed helpdesk support", 25, 45.00, "user per month", 12,
                 "Managed helpdesk support - 25 users at $45.00 per user per month"),
            item("Server and network monitoring", 1, 350.00, "month", 12,
                 "Server and network monitoring - flat $350.00 per month"),
            item("Cloud backup and recovery", 1, 180.00, "month", 12,
                 "Cloud backup and recovery - flat $180.00 per month"),
        ],
        "fees": [
            fee("Onboarding and network setup", 1500.00, False, 1,
                "Onboarding and network setup fee of $1,500.00 is due one time with the first invoice.",
                hidden=True),
        ],
        "tax": None,
        "terms": {
            "contract_months": term(12, "The initial term of this agreement is 12 months."),
            "payment_terms_days": term(30, "Invoices are payable net 30 days."),
        },
        "traps": ["hidden_setup_fee", "monthly_billing_units"],
    },
    {
        "file": "it_brightpath.pdf",
        "category": "it_support",
        "vendor": "BrightPath Technologies",
        "date": "October 8, 2026",
        "scope": "Full-service IT support package for 25 users.",
        "items": [
            item("Helpdesk and device support", 25, 480.00, "user per year", 1,
                 "Helpdesk and device support - 25 users at $480.00 per user per year"),
            item("Infrastructure monitoring", 1, 3600.00, "year", 1,
                 "Infrastructure monitoring - flat $3,600.00 per year"),
            item("Backup and disaster recovery", 1, 2000.00, "year", 1,
                 "Backup and disaster recovery - flat $2,000.00 per year"),
        ],
        "fees": [],
        "tax": (8.875, "Sales tax of 8.875% applies to all charges."),
        "terms": {
            "contract_months": term(36, "This agreement has a minimum term of 36 months."),
            "auto_renewal": term(
                True, "After the initial term this agreement renews automatically for successive 12 month terms."),
            "renewal_notice_days": term(
                90, "Written notice of non-renewal must be received at least 90 days before the term ends."),
            "payment_terms_days": term(15, "Annual invoices are payable net 15 days."),
        },
        "traps": ["auto_renewal", "long_lock_in", "annual_billing_units"],
    },
    {
        "file": "it_corestack.pdf",
        "category": "it_support",
        "vendor": "CoreStack Solutions",
        "date": "October 9, 2026",
        "scope": "Helpdesk and monitoring for a 25-person office.",
        "items": [
            item("Helpdesk support", 25, 38.00, "user per month", 12,
                 "Helpdesk support - 25 users at $38.00 per user per month"),
            item("Server monitoring", 1, 300.00, "month", 12,
                 "Server monitoring - flat $300.00 per month"),
        ],
        "fees": [],
        "tax": None,
        "terms": {
            "contract_months": term(12, "Contract length is 12 months from the start date."),
            "price_escalator_percent": term(
                6.0, "All recurring prices increase by 6% at the start of each contract year after the first."),
            "late_fee_percent": term(1.5, "Late payments accrue a fee of 1.5% per month."),
            "payment_terms_days": term(30, "Payment is due within 30 days of invoice."),
        },
        "traps": ["missing_item_backup", "price_escalator", "late_fee"],
    },
    # ------------------------------------------------------------- CLEANING
    {
        "file": "cleaning_sparkleworks.pdf",
        "category": "office_cleaning",
        "vendor": "SparkleWorks Cleaning Co.",
        "date": "October 12, 2026",
        "scope": "Office cleaning for an 8,000 sq ft office, 12 month service period.",
        "items": [
            item("Nightly office cleaning (3 visits per week, 52 weeks)", 156, 185.00, "visit", 1,
                 "Office cleaning, 3 visits per week for 52 weeks (156 visits) - $185.00 per visit"),
            item("Window cleaning (quarterly)", 4, 420.00, "visit", 1,
                 "Interior and exterior window cleaning, 4 visits per year - $420.00 per visit"),
        ],
        "fees": [
            fee("Initial deep clean", 650.00, False, 1,
                "A one-time initial deep clean of $650.00 will be added to the first invoice.",
                hidden=True),
        ],
        "tax": None,
        "terms": {
            "contract_months": term(12, "Service period: 12 months."),
            "auto_renewal": term(
                False, "This agreement ends at the end of the term and does not renew automatically."),
            "payment_terms_days": term(30, "Payment terms: net 30."),
        },
        "traps": ["hidden_one_time_fee", "per_visit_billing_units"],
    },
    {
        "file": "cleaning_cleanslate.pdf",
        "category": "office_cleaning",
        "vendor": "CleanSlate Facilities",
        "date": "October 13, 2026",
        "scope": "Flat-rate office cleaning program for an 8,000 sq ft office.",
        "items": [
            item("Office cleaning program (3 visits per week)", 1, 2150.00, "month", 12,
                 "Office cleaning program, 3 visits per week - flat $2,150.00 per month"),
        ],
        "fees": [],
        "tax": (8.875, "Sales tax of 8.875% will be added to each invoice."),
        "terms": {
            "contract_months": term(24, "The term of this agreement is 24 months."),
            "auto_renewal": term(
                True, "The agreement automatically renews for 12 month terms unless cancelled."),
            "renewal_notice_days": term(
                60, "Cancellation requires written notice at least 60 days before renewal."),
            "late_fee_percent": term(2.0, "A late fee of 2% per month applies to overdue balances."),
            "payment_terms_days": term(15, "Invoices are due net 15."),
        },
        "traps": ["auto_renewal", "long_lock_in", "missing_item_window_cleaning", "late_fee"],
    },
    {
        "file": "cleaning_evergreen.pdf",
        "category": "office_cleaning",
        "vendor": "Evergreen Janitorial",
        "date": "October 14, 2026",
        "scope": "Annual janitorial contract, 8,000 sq ft office.",
        "items": [
            item("Annual janitorial service (3 visits per week)", 1, 24000.00, "year", 1,
                 "Annual janitorial service, 3 visits per week - $24,000.00 per year, billed annually"),
            item("Window cleaning (quarterly)", 1, 1600.00, "year", 1,
                 "Quarterly window cleaning - $1,600.00 per year"),
        ],
        "fees": [
            fee("Fuel and equipment surcharge", 95.00, True, 12,
                "A fuel and equipment surcharge of $95.00 per month applies.",
                hidden=True, billing_unit="month"),
        ],
        "tax": None,
        "terms": {
            "contract_months": term(12, "Contract term: 12 months."),
            "price_escalator_percent": term(
                5.0, "Service rates increase 5% on each anniversary of the start date."),
            "payment_terms_days": term(30, "Payment due 30 days after invoice date."),
        },
        "traps": ["price_escalator", "hidden_recurring_fee", "annual_billing_units"],
    },
    # ------------------------------------------------------------- CATERING
    {
        "file": "catering_tableandfork.pdf",
        "category": "catering",
        "vendor": "Table & Fork Catering",
        "date": "October 19, 2026",
        "scope": "Weekly team lunch for 40 people, 48 lunches over 12 months.",
        "items": [
            item("Weekly team lunch", 1920, 18.50, "person per lunch", 1,
                 "Team lunch, 40 people x 48 lunches (1,920 meals) - $18.50 per person per lunch"),
            item("Coffee and beverage service", 1920, 2.50, "person per lunch", 1,
                 "Coffee and beverage service - $2.50 per person per lunch (1,920 servings)"),
        ],
        "fees": [
            fee("Delivery fee", 75.00, True, 48,
                "Delivery fee: $75.00 per lunch (48 lunches).",
                hidden=False, billing_unit="lunch", quantity=48),
        ],
        "tax": (8.875, "NYC sales tax of 8.875% applies to food and beverage."),
        "terms": {
            "contract_months": term(12, "Catering agreement term: 12 months."),
            "payment_terms_days": term(30, "Payment is due net 30."),
        },
        "traps": ["per_person_per_event_units", "recurring_delivery_fee"],
    },
    {
        "file": "catering_harvestkitchen.pdf",
        "category": "catering",
        "vendor": "Harvest Kitchen",
        "date": "October 20, 2026",
        "scope": "Weekly team lunch for 40 people, 48 lunches over 12 months.",
        "items": [
            item("Weekly team lunch", 1920, 16.00, "person per lunch", 1,
                 "Team lunch, 40 people x 48 lunches (1,920 meals) - $16.00 per person per lunch"),
            item("Beverage package", 1920, 2.00, "person per lunch", 1,
                 "Beverage package - $2.00 per person per lunch (1,920 servings)"),
        ],
        "fees": [
            fee("Equipment and setup", 900.00, False, 1,
                "Equipment and setup charge of $900.00 is billed once at program start.",
                hidden=True),
        ],
        "tax": None,
        "terms": {
            "contract_months": term(12, "Initial term: 12 months."),
            "auto_renewal": term(
                True, "This agreement renews automatically for another 12 months at the end of the term."),
            "renewal_notice_days": term(
                30, "Notice of cancellation must be given at least 30 days before renewal."),
            "price_escalator_percent": term(
                3.0, "Per-person prices increase by 3% each January."),
            "late_fee_percent": term(1.5, "Overdue invoices incur a 1.5% monthly late fee."),
            "payment_terms_days": term(15, "Payment is due 15 days from invoice."),
        },
        "traps": ["hidden_setup_fee", "auto_renewal", "price_escalator", "late_fee"],
    },
    {
        "file": "catering_urbanplate.pdf",
        "category": "catering",
        "vendor": "Urban Plate Co.",
        "date": "October 21, 2026",
        "scope": "Monthly lunch package for a 40-person team.",
        "items": [
            item("Monthly lunch package (4 lunches for up to 40 people)", 1, 3100.00, "month", 12,
                 "Monthly lunch package, 4 lunches for up to 40 people - $3,100.00 per month"),
        ],
        "fees": [],
        "tax": None,
        "terms": {
            "contract_months": term(12, "Package term: 12 months."),
            "auto_renewal": term(
                True, "The package renews automatically each year."),
            "renewal_notice_days": term(
                60, "Cancel at least 60 days before the renewal date to avoid renewal."),
            "payment_terms_days": term(15, "Invoices are payable within 15 days."),
        },
        "traps": ["auto_renewal", "missing_item_beverages", "monthly_package_units"],
    },
]


# ---------------------------------------------------------------- rendering

def build_pdf(q: dict, path: Path) -> None:
    ss = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=ss["Title"], textColor=colors.HexColor("#1f3a5f"), fontSize=20)
    h = ParagraphStyle("h", parent=ss["Heading2"], textColor=colors.HexColor("#1f3a5f"), spaceBefore=10)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=10, leading=14)
    fine = ParagraphStyle("f", parent=body, fontSize=8, leading=11, textColor=colors.HexColor("#444444"))

    def p(text, style=body):
        return Paragraph(escape(text), style)

    story = [
        p(q["vendor"], title),
        p(f"Quotation dated {q['date']}"),
        p(q["scope"]),
        Spacer(1, 6),
        p("Scope and Pricing", h),
    ]
    for it in q["items"]:
        story.append(p(it["source_snippet"]))
    if q["tax"]:
        story.append(p(q["tax"][1]))
    else:
        story.append(p("Prices shown are exclusive of applicable taxes."))

    visible_fees = [f for f in q["fees"] if not f["hidden_in_fine_print"]]
    if visible_fees:
        story.append(p("Additional Charges", h))
        for f in visible_fees:
            story.append(p(f["source_snippet"]))

    story.append(p("Terms and Conditions", h))
    for key in TERM_KEYS:
        if key in q["terms"]:
            story.append(p(q["terms"][key]["source_snippet"]))

    hidden_fees = [f for f in q["fees"] if f["hidden_in_fine_print"]]
    story.append(Spacer(1, 14))
    story.append(p("General Provisions", h))
    story.append(p("Standard business hours apply. Services are subject to the vendor's "
                   "master services agreement. Either party may raise scope changes in writing.", fine))
    for f in hidden_fees:
        story.append(p(f["source_snippet"], fine))
    story.append(p("This quotation is valid for 30 days from the date above. "
                   "This document is a fictional sample created for software testing.", fine))

    SimpleDocTemplate(
        str(path), pagesize=letter, title=f"{q['vendor']} quotation",
        leftMargin=inch, rightMargin=inch, topMargin=inch, bottomMargin=inch,
    ).build(story)


def expected_json(q: dict) -> dict:
    annual = 0.0
    items = []
    for it in q["items"]:
        annual += it["quantity"] * it["unit_price"] * it["annual_multiplier"]
        items.append(dict(it))
    fees = []
    for f in q["fees"]:
        annual += f["amount"] * (f["annual_multiplier"] if f["recurring"] else 1)
        fees.append(dict(f))

    terms = {}
    for key in TERM_KEYS:
        if key in q["terms"]:
            terms[key] = q["terms"][key]
        else:
            terms[key] = {"value": None, "source_snippet": None, "status": "not found"}

    if q["tax"]:
        tax = {"rate_percent": q["tax"][0], "source_snippet": q["tax"][1]}
    else:
        tax = {"rate_percent": None, "source_snippet": None, "status": "not found"}

    return {
        "file": q["file"],
        "category": q["category"],
        "vendor": q["vendor"],
        "line_items": items,
        "fees": fees,
        "tax": tax,
        "terms": terms,
        "expected_first_year_pretax_total": round(annual, 2),
        "traps": q["traps"],
    }


def verify(q: dict, pdf_path: Path) -> list[str]:
    """Return snippets that do not appear in the extracted PDF text."""
    with pdfplumber.open(pdf_path) as pdf:
        text = " ".join((page.extract_text() or "") for page in pdf.pages)
    norm = re.sub(r"\s+", " ", text)
    snippets = [it["source_snippet"] for it in q["items"]]
    snippets += [f["source_snippet"] for f in q["fees"]]
    snippets += [t["source_snippet"] for t in q["terms"].values()]
    if q["tax"]:
        snippets.append(q["tax"][1])
    return [s for s in snippets if re.sub(r"\s+", " ", s) not in norm]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="tests/fixtures", help="output directory")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    failed = False
    for q in QUOTES:
        pdf_path = out / q["file"]
        build_pdf(q, pdf_path)
        data = expected_json(q)
        (out / q["file"].replace(".pdf", ".expected.json")).write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )
        missing = verify(q, pdf_path)
        status = "ok" if not missing else "MISSING SNIPPETS"
        print(f"{q['file']:34} total ${data['expected_first_year_pretax_total']:>10,.2f}  {status}")
        for m in missing:
            failed = True
            print(f"    not found in PDF text: {m}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
