import re

INJECTION = re.compile(r"\b(ignore|disregard|override)\b.{0,80}\b(instructions|rules|policy)\b|\b(bulk|all)\b.{0,40}\b(approve|authorize)\b|\b(reveal|show|send)\b.{0,40}\b(other patients|system prompt|hidden data)\b", re.I)
THIRD_PARTY_RELATION = re.compile(r"\b(?:neighbor|neighbour|friend|coworker|colleague)\b", re.I)

def suspicious_instruction(text: str) -> bool:
    return bool(INJECTION.search(text))


def identity_conflict(text: str, patient_name: str) -> bool:
    """Block a form identity match when the message says the sender is someone else."""
    normalized = text.replace("’", "'").replace("‘", "'")
    name = re.escape(patient_name.strip())
    denial = re.search(rf"\b(?:i am not|i'm not|im not)\s+(?:the patient\s+)?{name}(?![\w])", normalized, re.I)
    relation = THIRD_PARTY_RELATION.search(normalized)
    refers_to_patient = re.search(rf"\b(?:his|her|their)\b|\b{name}\b", normalized, re.I)
    first_person = re.search(r"\b(?:i am|i'm|im)\b", normalized, re.I)
    return bool(denial or (relation and refers_to_patient and first_person))
