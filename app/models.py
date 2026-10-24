from typing import Literal
from pydantic import BaseModel, Field, ConfigDict

Urgency = Literal["emergency", "urgent", "routine"]
Action = Literal[
    "escalate_emergency", "route_to_clinician", "route_to_provider", "route_to_billing",
    "route_to_front_desk", "prepare_refill_for_approval", "refill_needs_visit",
    "refill_too_early", "book_appointment", "reschedule_appointment", "cancel_appointment",
    "offer_appointment", "offer_alternatives", "offer_new_patient_booking",
    "request_verification", "decline_disclosure", "flag_suspicious_instruction",
    "answer_directly", "acknowledge", "no_action",
]
Queue = Literal["clinician_urgent", "clinician_routine", "provider_refills", "front_desk", "billing"]

class IncomingMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    received_at: str = ""
    channel: str = ""
    from_name: str
    from_contact: str
    body: str = Field(max_length=5000)
    stated_dob: str | None = None

class AgentResult(BaseModel):
    id: str
    patient_id: str | None = None
    intents: list[str]
    urgency: Urgency
    actions: list[Action]
    routed_to: list[Queue]
    tool_calls: list[str]
    reply_draft: str
    verified: bool = False
    trace: list[dict] = Field(default_factory=list)
    model_status: str = "offline"
    errors: list[str] = Field(default_factory=list)
