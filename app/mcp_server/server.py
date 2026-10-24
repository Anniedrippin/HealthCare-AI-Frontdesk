from pydantic import BaseModel, Field
from typing import Literal
from mcp.server.fastmcp import FastMCP
from app.services.domain import ClinicStore
from app.guardrails.policy_enforcement import refill_decision

store = ClinicStore()
mcp = FastMCP("Healthcare AI Clinic Tools")

class FindPatientArgs(BaseModel): name: str = Field(min_length=2, max_length=100); contact: str = ""
class AuthArgs(BaseModel): patient_id: str; sender_name: str; contact: str; dob: str | None = None
class RefillArgs(AuthArgs): medication: str
class SlotArgs(BaseModel): provider: str; start_date: str; visit_type: str; part_of_day: str | None = None
class BookArgs(AuthArgs): provider: str; date: str; start: str; visit_type: str; idempotency_key: str = Field(min_length=1,max_length=120)
class CancelArgs(AuthArgs): appointment_id: str; idempotency_key: str = Field(min_length=1,max_length=120)
class RescheduleArgs(BookArgs): appointment_id: str
class RouteArgs(BaseModel): queue: Literal["clinician_urgent","clinician_routine","provider_refills","front_desk","billing"]; message_id: str = Field(min_length=1,max_length=80); summary: str = Field(max_length=300)
class DraftArgs(BaseModel): reply: str = Field(max_length=1200)

@mcp.tool()
def find_patient(args: FindPatientArgs) -> dict:
    """Find one patient by full name or on-file contact; does not authorize access."""
    p=store.find_patient(args.name)
    if not p and args.contact:
        matches=[x for x in store.patients if args.contact.casefold() in {x.get("phone","").casefold(),x.get("email","").casefold(),(x.get("authorised_caregiver") or {}).get("phone","").casefold()}]
        p=matches[0] if len(matches)==1 else None
    return {"patient_id":p["id"],"name":p["name"]} if p else {"found":False}

@mcp.tool()
def verify_patient_or_caregiver(args: AuthArgs) -> dict:
    """Verify by matching contact on file or exact patient name and DOB."""
    return store.authorize(args.patient_id,args.sender_name,args.contact,args.dob)

@mcp.tool()
def read_patient_medications(args: AuthArgs) -> list[dict]:
    """Read medications only after patient/caregiver authorization."""
    return store.permitted_medications(args.patient_id,args.sender_name,args.contact,args.dob)

@mcp.tool()
def check_refill_eligibility(args: RefillArgs) -> dict:
    """Check refill policy after verifying the requester."""
    if not store.authorize(args.patient_id,args.sender_name,args.contact,args.dob)["verified"]: raise PermissionError("Verification required")
    return refill_decision(store,args.patient_id,args.medication)

@mcp.tool()
def find_available_appointment_slots(args: SlotArgs) -> list[dict]:
    """Find slots while applying clinic hours, duration, holidays, leave and conflicts."""
    return store.find_slots(args.provider,args.start_date,args.visit_type,args.part_of_day)

@mcp.tool()
def book_appointment(args: BookArgs) -> dict:
    """Commit a checked appointment booking with an idempotency key."""
    if not store.authorize(args.patient_id,args.sender_name,args.contact,args.dob)["verified"]: raise PermissionError("Verification required")
    return store.book(args.patient_id,args.provider,args.date,args.start,args.visit_type,args.idempotency_key)

@mcp.tool()
def cancel_appointment(args: CancelArgs) -> dict:
    """Cancel a booked appointment belonging to the verified patient."""
    if not store.authorize(args.patient_id,args.sender_name,args.contact,args.dob)["verified"]: raise PermissionError("Verification required")
    return store.cancel(args.appointment_id,args.patient_id,args.idempotency_key)

@mcp.tool()
def reschedule_appointment(args: RescheduleArgs) -> dict:
    """Move a patient's existing appointment after rechecking the destination slot."""
    if not store.authorize(args.patient_id,args.sender_name,args.contact,args.dob)["verified"]: raise PermissionError("Verification required")
    return store.reschedule(args.appointment_id,args.patient_id,args.provider,args.date,args.start,args.visit_type,args.idempotency_key)

@mcp.tool()
def route_message(args: RouteArgs) -> dict:
    """Route a minimum-necessary summary to a clinic human queue."""
    if args.queue not in store.clinic["routing_queues"]: raise ValueError("Unknown queue")
    return {"queued":True,"queue":args.queue,"message_id":args.message_id,"summary":args.summary[:300]}

@mcp.tool()
def draft_reply(args: DraftArgs) -> dict:
    """Wrap an already policy-checked reply draft for presentation."""
    return {"reply_draft":args.reply[:1200]}

if __name__ == "__main__":
    mcp.run()
