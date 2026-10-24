from app.models import AgentResult

def validate_result(result: dict) -> AgentResult:
    parsed=AgentResult.model_validate(result)
    if parsed.patient_id is not None and not parsed.verified:
        raise ValueError("Unverified sender cannot receive a patient_id")
    successful={x.get("tool") for x in parsed.trace if x.get("status")=="success"}
    delivered={x.get("result",{}).get("queue") for x in parsed.trace if x.get("tool")=="route_message" and x.get("status")=="success" and isinstance(x.get("result"),dict)}
    if not set(parsed.routed_to).issubset(delivered):
        raise ValueError("Routed queues must have successful route tool results")
    operation_tools={"book_appointment":"book_appointment","reschedule_appointment":"reschedule_appointment","cancel_appointment":"cancel_appointment"}
    for action,tool in operation_tools.items():
        if action in parsed.actions and tool not in successful:
            raise ValueError(f"Claimed {action} without successful tool result")
    refill_checks=[x.get("result") for x in parsed.trace if x.get("tool")=="check_refill_eligibility" and x.get("status")=="success" and isinstance(x.get("result"),dict)]
    if "prepare_refill_for_approval" in parsed.actions and not any(x.get("eligible") is True for x in refill_checks):
        raise ValueError("Refill preparation requires a successful eligible policy result")
    if "refill_too_early" in parsed.actions and not any(x.get("reason")=="too_early" and x.get("earliest_date") for x in refill_checks):
        raise ValueError("Early refill response requires the policy-provided date")
    if "refill_needs_visit" in parsed.actions and not any(x.get("reason")=="needs_visit" for x in refill_checks):
        raise ValueError("Visit requirement must come from the refill policy tool")
    if parsed.urgency=="emergency":
        if "escalate_emergency" not in parsed.actions or "clinician_urgent" not in parsed.routed_to:
            raise ValueError("Emergency output must be escalated to clinician_urgent")
        text=parsed.reply_draft.lower()
        if not any(x in text for x in ["911","emergency department"]) or any(x in text for x in ["take ","you have","diagnosis"]):
            raise ValueError("Emergency reply exceeds the clinic's limited emergency response")
    return parsed
