"""Simulated payment gateway (sandbox). Outcomes depend on the sandbox token, as in real
provider sandboxes; the token lists live in config/business.yaml (payments.sandbox_tokens)."""
import secrets
import time
from dataclasses import dataclass
from decimal import Decimal

from config.loader import business


@dataclass(frozen=True)
class GatewayResult:
    success: bool
    reference: str
    error_code: str = ""
    message: str = ""


class SandboxGateway:
    def __init__(self):
        cfg = business()["payments"]
        self.tokens = cfg["sandbox_tokens"]
        self.latency = cfg["latency_seconds"]

    def _ref(self, prefix: str) -> str:
        return f"{prefix}_{secrets.token_hex(10)}"

    def charge(self, amount: Decimal, token: str) -> GatewayResult:
        if self.latency:
            time.sleep(self.latency)
        if amount <= 0:
            return GatewayResult(False, "", "invalid_amount", "Amount must be positive.")
        if token in self.tokens["success"]:
            return GatewayResult(True, self._ref("ch"), message="Approved")
        if token in self.tokens["declined"]:
            return GatewayResult(False, self._ref("ch"), "card_declined", "The card was declined.")
        if token in self.tokens["insufficient_funds"]:
            return GatewayResult(False, self._ref("ch"), "insufficient_funds", "Insufficient funds.")
        return GatewayResult(False, "", "invalid_token", "Unknown sandbox payment token.")

    def refund(self, reference: str, amount: Decimal) -> GatewayResult:
        return GatewayResult(True, self._ref("re"), message=f"Refunded {amount} for {reference}")


gateway = SandboxGateway()
