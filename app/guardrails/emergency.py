import re

_NEG = re.compile(r"\b(no|not|never|denies|without|wasn't|isn't|aren't|don't|doesn't)\b(?:\W+\w+){0,3}\W+(?:having|experiencing|feeling|any)?\W*", re.I)
_HIGH_RISK = [
    re.compile(r"\b(crushing|severe|pressure|tightness).{0,25}\b(chest|heart)\b|\b(chest|heart).{0,25}\b(crushing|severe|pressure|pain)\b", re.I),
    re.compile(r"\b(can't|cannot|unable to)\b.{0,30}\b(breathe|finish sentences|speak)\b|\b(gasping|blue lips|not breathing)\b", re.I),
    re.compile(r"\b(fell|fall|hit|injury).{0,50}\b(head|confused|unconscious|passed out)\b|\b(head injury|hit (her|his|my) head).{0,50}\b(confus|vomit|unconscious)\w*", re.I),
    re.compile(r"\b(bleeding (a lot|heavily|won't stop)|dark stools|black stools|vomiting blood)\b", re.I),
    re.compile(r"\b(blood sugar|glucose).{0,20}\b(3[0-9]|4[0-9]|5[0-4])\b|\b(shaky and sweaty|seizure|unresponsive)\b", re.I),
    re.compile(r"\b(suicid\w*|kill myself|end my life|don't see the point of anything)\b", re.I),
    re.compile(r"\b(one[- ]sided weakness|sudden weakness|can't speak clearly)\b|\b(face|speech).{0,18}\b(droop\w*|slur\w*)\b|\b(droop\w*|slur\w*).{0,18}\b(face|speech)\b", re.I),
    re.compile(r"\b(throat|tongue|face).{0,25}\b(swelling|swollen)\b.{0,35}\b(breath|airway|swallow)\b|\banaphylaxis\b", re.I),
    re.compile(r"\b(overdose|poisoned|took too many|took too much|not waking up|lost consciousness|passed out and)\b", re.I),
]
_NEGATION_EXCEPT = re.compile(r"\b(no|not|never|denies|without)\b.{0,24}\b(chest pain|shortness of breath|bleeding|suicidal|wheezing)\b", re.I)
_IDIOM = re.compile(r"\b(i'm|i am) dying to\b|\bdying to get in\b", re.I)

def emergency_status(text: str) -> tuple[bool, bool]:
    """Return (emergency, uncertain_high_risk); conservative, contextual checks."""
    if _IDIOM.search(text) and not re.search(r"\b(chest|breath|blood|unconscious|suicid)\b", text, re.I):
        return False, False
    if _NEGATION_EXCEPT.search(text):
        return False, False
    hits = sum(bool(p.search(text)) for p in _HIGH_RISK)
    if hits:
        # Mood language without explicit imminent intent is same-day clinician escalation.
        if re.search(r"\b(suicid\w*|kill myself|end my life|going to hurt myself|about to hurt myself)\b", text, re.I):
            return True, False
        if re.search(r"\bdon't see the point of anything\b", text, re.I):
            return False, False
        return True, False
    if re.search(r"\b(chest pain|shortness of breath|severe pain|confus\w*|bleed\w*)\b", text, re.I):
        if not _NEGATION_EXCEPT.search(text):
            return False, True
    return False, False
