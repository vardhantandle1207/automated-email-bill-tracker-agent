"""Typed schema for the fields the agent extracts from an invoice email.

Passing this Pydantic model to Gemini as a response_schema forces the model to
return exactly these fields as JSON — no prompt-parsing, no regex.
"""

from typing import Optional

from pydantic import BaseModel, Field


class InvoiceFields(BaseModel):
    vendor: str = Field(description="The company or service that issued the bill, e.g. 'Netflix'")
    amount: float = Field(description="Numeric amount due, no currency symbol or commas")
    currency: str = Field(description="ISO 4217 code inferred from the email, e.g. INR, USD, EUR")
    due_date: Optional[str] = Field(
        default=None,
        description="Due date as YYYY-MM-DD, or null if the email states none",
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
