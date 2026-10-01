"""Typed schema for the fields the agent extracts from an invoice email.

Passing this Pydantic model to Gemini as a response_schema forces the model to
return exactly these fields as JSON — no prompt-parsing, no regex.
"""

from typing import Optional

from pydantic import BaseModel, Field


class InvoiceFields(BaseModel):
    is_bill: bool = Field(
        default=True,
        description="True if the email is a bill, invoice, statement with an amount due, or a "
        "receipt/renewal notice for a recurring service or subscription. False for anything "
        "else: promotions and sales, newsletters, shipping or delivery updates, card "
        "transaction alerts, and price-change notices. If False, the other fields are "
        "ignored (use vendor of the sender, amount 0, currency INR).",
    )
    vendor: str = Field(description="The company or service that issued the bill, e.g. 'Netflix'")
    amount: float = Field(description="Numeric total amount due or charged, no currency symbol or commas")
    currency: str = Field(description="ISO 4217 code inferred from the email, e.g. INR, USD, EUR")
    due_date: Optional[str] = Field(
        default=None,
        description="YYYY-MM-DD date by which this bill must be paid or will be charged. "
        "For a receipt of a recurring subscription, use the next billing or renewal date "
        "written in the email. null only if the email states no such date.",
    )
    paid: bool = Field(
        default=False,
        description="True only if the email confirms the payment already went through "
        "(a receipt). False if it asks for payment or says it will be charged later.",
    )
    autopay: bool = Field(
        default=False,
        description="True only if the email says THIS amount will be charged or debited "
        "automatically (auto-pay, card on file, auto-debit), so the user need not pay it. "
        "False for receipts of payments already made and for bills the user must pay.",
    )


class BatchInvoice(InvoiceFields):
    """One item of a batched extraction; email_id ties it back to its email."""

    email_id: int = Field(description="The number n from this email's '=== EMAIL n ===' header")
