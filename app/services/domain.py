import json, os, re
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import RLock

class ClinicStore:
    def __init__(self, data_dir: str | Path | None = None):
        base = Path(data_dir or os.getenv("DATA_DIR", "data"))
        def load(name):
            with (base / name).open(encoding="utf-8") as f: return json.load(f)
        self.clinic = load("clinic.json"); self.patients = load("patients.json")
        self.medications = load("medications.json"); self.appointments = load("appointments.json")
        self.messages = load("messages_sample.json"); self.labels = load("labels_sample.json")
        self.today = date.fromisoformat(self.clinic["today"])
        self._lock = RLock(); self._idempotency: dict[str,dict] = {}; self.traces: dict[str,list] = {}

    def patient(self, patient_id):
        return next((p for p in self.patients if p["id"] == patient_id), None)

    def find_patient(self, name: str):
        q = re.sub(r"[^a-z0-9 ]", "", name.casefold()).strip()
        hits = [p for p in self.patients if q and q in re.sub(r"[^a-z0-9 ]", "", p["name"].casefold())]
        return hits[0] if len(hits) == 1 else None

    def authorize(self, patient_id, sender_name, contact, dob=None):
        p = self.patient(patient_id)
        if not p: return {"verified": False, "reason": "patient_not_found"}
        contact = (contact or "").strip().casefold()
        patient_contact = contact in {p.get("phone", "").casefold(), p.get("email", "").casefold()}
        caregiver = p.get("authorised_caregiver") or {}
        caregiver_contact = contact == caregiver.get("phone", "").casefold()
        name_dob = sender_name.strip().casefold() == p["name"].casefold() and dob == p["dob"]
        caregiver_name = sender_name.strip().casefold() == caregiver.get("name", "").casefold()
        verified = patient_contact or caregiver_contact or name_dob
        return {"verified": verified, "patient_id": patient_id if verified else None,
                "authorized_caregiver": verified and caregiver_contact or (verified and caregiver_name),
                "reason": "verified" if verified else "verification_required"}

    def permitted_medications(self, patient_id, sender_name, contact, dob=None):
        auth = self.authorize(patient_id, sender_name, contact, dob)
        if not auth["verified"]: raise PermissionError("Patient verification required")
        return [m for m in self.medications if m["patient_id"] == patient_id]

    def _provider(self, provider_id):
        return next((p for p in self.clinic["providers"] if p["id"] == provider_id), None)

    def slot_valid(self, provider, day, start, visit_type, ignore_id=None):
        p = self._provider(provider)
        if not p or visit_type not in self.clinic["visit_types"]: return False
        d = date.fromisoformat(day); duration = self.clinic["visit_types"][visit_type]
        if d < self.today or d.isoformat() in self.clinic["holidays"] or d.strftime("%a") not in self.clinic["hours"]["days"]: return False
        for a,b in p.get("leave", []):
            if date.fromisoformat(a) <= d <= date.fromisoformat(b): return False
        st = datetime.strptime(start, "%H:%M"); end = st + timedelta(minutes=duration)
        op = datetime.strptime(self.clinic["hours"]["open"], "%H:%M"); close = datetime.strptime(self.clinic["hours"]["close"], "%H:%M")
        lunch_s,lunch_e = [datetime.strptime(x,"%H:%M") for x in self.clinic["hours"]["lunch"]]
        if st.minute not in {0,20,40} or st < op or end > close or (st < lunch_e and end > lunch_s): return False
        for a in self.appointments:
            if a["status"] != "booked" or a["provider"] != provider or a["date"] != day or a["id"] == ignore_id: continue
            a_s=datetime.strptime(a["start"],"%H:%M"); a_e=datetime.strptime(a["end"],"%H:%M")
            if st < a_e and end > a_s: return False
        return True

    def find_slots(self, provider, start_date, visit_type, part_of_day=None, limit=5):
        result=[]; start=date.fromisoformat(start_date)
        for offset in range(42):
            d=start+timedelta(days=offset)
            for hour in range(9,17):
                for minute in (0,20,40):
                    if hour==12: continue
                    t=f"{hour:02d}:{minute:02d}"
                    if part_of_day=="morning" and hour>=12 or part_of_day=="afternoon" and hour<13: continue
                    if self.slot_valid(provider,d.isoformat(),t,visit_type):
                        result.append({"provider":provider,"date":d.isoformat(),"start":t,"visit_type":visit_type})
                        if len(result)>=limit:return result
        return result

    def book(self, patient_id, provider, day, start, visit_type, key):
        with self._lock:
            if key in self._idempotency:return self._idempotency[key]
            if not self.slot_valid(provider,day,start,visit_type): raise ValueError("Slot unavailable or violates clinic policy")
            duration=self.clinic["visit_types"][visit_type]
            end=(datetime.strptime(start,"%H:%M")+timedelta(minutes=duration)).strftime("%H:%M")
            record={"id":f"RUN{len(self.appointments)+1:03d}","patient_id":patient_id,"provider":provider,"date":day,"start":start,"end":end,"visit_type":visit_type,"status":"booked"}
            self.appointments.append(record); self._idempotency[key]=record; return record

    def cancel(self, appointment_id, patient_id, key):
        with self._lock:
            if key in self._idempotency:return self._idempotency[key]
            a=next((a for a in self.appointments if a["id"]==appointment_id and a["patient_id"]==patient_id and a["status"]=="booked"),None)
            if not a: raise ValueError("Booked appointment not found for patient")
            a["status"]="cancelled"; self._idempotency[key]=a; return a

    def reschedule(self, appointment_id, patient_id, provider, day, start, visit_type, key):
        with self._lock:
            if key in self._idempotency:return self._idempotency[key]
            old=next((a for a in self.appointments if a["id"]==appointment_id and a["patient_id"]==patient_id and a["status"]=="booked"),None)
            if not old: raise ValueError("Booked appointment not found for patient")
            if not self.slot_valid(provider,day,start,visit_type,ignore_id=appointment_id): raise ValueError("Requested slot unavailable")
            old["status"]="rescheduled"
            result=self.book(patient_id,provider,day,start,visit_type,key)
            self._idempotency[key]=result; return result
