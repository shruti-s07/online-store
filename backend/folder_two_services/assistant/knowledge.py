"""Knowledge base for customer store inquiries and out-of-box questions."""
from __future__ import annotations

import re


def get_faq_answer(text: str) -> str | None:
    """Answers common store policy, support, and out-of-box customer questions.
    Returns None if the question is an e-commerce action or unhandled.
    """
    t = text.lower().strip()

    # 1. SnapCheck & Return Verification
    if re.search(r"\b(?:snapcheck|snap check|image ai|wrong item|photo return|verify return)\b", t):
        return (
            "SnapCheck is our AI-powered return verification feature. When you request a return, "
            "simply upload a photo of the received item. Our pretrained CLIP vision model compares it "
            "against the official product listing photo. Clear mismatches or incorrect items are fast-tracked "
            "directly to staff review for prompt approval!"
        )

    # 2. Refund & Return Policies
    if re.search(r"\b(?:refund|refunds|return policy|return window|return process|how to return|send back)\b", t):
        return (
            "We offer a 7-day return window from the date of delivery. If you received a wrong, damaged, "
            "or defective product, you can initiate a return in the 'Orders' tab using SnapCheck photo verification. "
            "Once approved, refunds are processed within 24 to 48 hours to your original payment method or UPI."
        )

    # 3. Cash on Delivery (COD) & Payments
    if re.search(r"\b(?:cod|cash on delivery|pay on delivery|payment methods?|upi|google pay|phonepe|paytm|cards?|net banking)\b", t):
        return (
            "Yes! We support Cash on Delivery (COD) across all serviceable PIN codes in India. "
            "We also accept UPI (Google Pay, PhonePe, Paytm, BHIM), Credit and Debit cards (Visa, MasterCard, RuPay), "
            "and Net Banking at checkout."
        )

    # 4. Stock Reservation & Expiry
    if re.search(r"\b(?:stock reserv\w+|reserv\w+ expir\w+|cart expir\w+|reserved items?|hold stock)\b", t):
        return (
            "Items added to your checkout session are softly reserved for 15 minutes. "
            "This protects you from out-of-stock surprises during high-demand rushes while ensuring items "
            "aren't locked indefinitely if not purchased."
        )

    # 5. Shipping & Delivery
    if re.search(r"\b(?:shipping|delivery time|delivery charges?|when will (?:it|package) deliver|how long does delivery take|pan india|deliver across)\b", t):
        return (
            "We deliver pan-India covering all 36 States and Union Territories. Standard delivery takes "
            "3 to 5 business days, and shipping is completely free for all orders!"
        )

    # 6. Fraud Screening & Security
    if re.search(r"\b(?:fraud|risk score|why on hold|order on hold|otp check|security)\b", t):
        return (
            "Every order is screened using an AI anomaly model to protect buyers and sellers from fraud. "
            "Orders with high risk or address mismatches are placed 'ON_HOLD' for staff review or sent an OTP check "
            "to ensure secure and reliable delivery."
        )

    # 7. About Haat / Identity
    if re.search(r"\b(?:who are you|what is haat|about haat|about this store|what can you do|your name)\b", t):
        return (
            "I am your AI Shopping Assistant at Haat! Haat is a curated Indian online marketplace "
            "bringing you quality lifestyle, electronics, fashion, and home essentials directly from trusted makers. "
            "I can help you search products, recommend top items, manage your cart, check order statuses, "
            "and answer any questions about our store policies."
        )

    # 8. Greetings & Chit-chat
    if re.search(r"^(?:hi|hello|hey|good\s+(?:morning|afternoon|evening)|namaste)\b", t):
        return (
            "Namaste! Welcome to Haat. How can I assist your shopping today? "
            "You can ask me to search products, suggest recommendations, or check your cart and orders."
        )
    if re.search(r"\b(?:thank you|thanks|great|awesome|helpful)\b", t):
        return "You're very welcome! Let me know if you need help finding anything else on Haat. Happy shopping!"

    # 9. Clear Out-of-Domain queries (e.g. general knowledge, weather, code)
    if re.search(r"\b(?:weather|temperature|prime minister|president|code in python|write code|capital of|movie|song)\b", t):
        return (
            "I'm specifically designed to help you shop at Haat! While I can't answer general trivia, "
            "I can help you browse our catalogue, check prices, track orders, or explain our return and COD policies. "
            "What kind of product are you looking for today?"
        )

    return None
