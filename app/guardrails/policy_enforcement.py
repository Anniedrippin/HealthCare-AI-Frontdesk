from datetime import date, timedelta

def refill_decision(store, patient_id: str, medication_query: str) -> dict:
    patient = store.patient(patient_id)
    meds = [m for m in store.medications if m["patient_id"] == patient_id and medication_query.casefold() in m["medication"].casefold()]
    if not meds:
        return {"eligible": False, "reason": "not_found"}
    med = meds[0]
    if med.get("controlled_schedule"):
        return {"eligible": False, "reason": "controlled", "medication": med["medication"]}
    if (store.today - date.fromisoformat(patient["last_visit"])).days > 365:
        return {"eligible": False, "reason": "needs_visit", "medication": med["medication"]}
    if med["refills_remaining"] <= 0:
        return {"eligible": False, "reason": "no_refills", "medication": med["medication"]}
    supply_end = date.fromisoformat(med["last_filled"]) + timedelta(days=int(med["days_supply"]))
    earliest = supply_end - timedelta(days=7)
    if store.today < earliest:
        return {"eligible": False, "reason": "too_early", "earliest_date": earliest.isoformat(), "medication": med["medication"]}
    return {"eligible": True, "reason": "eligible", "medication": med["medication"], "approval_required": True}
