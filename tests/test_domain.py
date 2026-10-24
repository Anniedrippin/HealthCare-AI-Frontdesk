from app.services.domain import ClinicStore
from app.guardrails.policy_enforcement import refill_decision
import pytest

def test_identity_and_caregiver():
    s=ClinicStore()
    assert s.authorize("P002","Robert Chen","555-0102")["verified"]
    assert s.authorize("P002","Robert Chen","new@example.com","1971-11-02")["verified"]
    assert not s.authorize("P002","Robert Chen","new@example.com","1971-11-20")["verified"]
    assert s.authorize("P017","Claire Ellis","555-0177")["verified"]

def test_refill_rules():
    s=ClinicStore()
    assert refill_decision(s,"P006","Alprazolam")["reason"]=="controlled"
    assert refill_decision(s,"P008","Amlodipine")["reason"]=="no_refills"
    assert refill_decision(s,"P004","Metformin")["reason"]=="needs_visit"
    assert refill_decision(s,"P015","Omeprazole")["reason"]=="too_early"
    assert refill_decision(s,"P002","Lisinopril")["eligible"]

def test_schedule_leave_conflict_holiday_and_idempotency():
    s=ClinicStore()
    assert not s.slot_valid("OKAFOR","2026-11-18","10:00","follow_up")
    assert not s.slot_valid("PATEL","2026-11-26","10:00","follow_up")
    assert not s.slot_valid("OKAFOR","2026-11-12","14:00","follow_up")
    rec=s.book("P002","PATEL","2026-11-30","09:00","follow_up","same")
    assert s.book("P002","PATEL","2026-11-30","09:00","follow_up","same")==rec
    with pytest.raises(ValueError): s.book("P003","PATEL","2026-11-30","09:00","follow_up","other")

def test_invalid_cancel_and_reschedule_are_rejected():
    s=ClinicStore()
    with pytest.raises(ValueError): s.cancel("missing","P002","cancel-key")
    with pytest.raises(ValueError): s.reschedule("missing","P002","PATEL","2026-11-30","09:00","follow_up","move-key")
    with pytest.raises(ValueError): s.reschedule("A001","P019","OKAFOR","2026-11-18","09:00","follow_up","leave-key")
