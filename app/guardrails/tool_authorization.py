from app.services.domain import ClinicStore

def require_verified(store: ClinicStore, patient_id: str, sender_name: str, contact: str, dob: str | None = None) -> dict:
    return store.authorize(patient_id, sender_name, contact, dob)
