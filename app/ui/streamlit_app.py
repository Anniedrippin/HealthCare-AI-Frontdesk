import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import streamlit as st
from app.agent.processor import Agent
from app.services.domain import ClinicStore

st.set_page_config(page_title="Maplewood Front Desk",page_icon="🏥",layout="wide")
st.title("Maplewood Family Clinic · AI Front Desk")
st.caption("Synthetic-data take-home prototype · not for real patient care")
if "agent" not in st.session_state: st.session_state.agent=Agent(ClinicStore())
agent=st.session_state.agent
tab1,tab2,tab3=st.tabs(["Process message","Sample inbox","Evaluation"])
with tab1:
    with st.form("message"):
        a,b=st.columns(2); mid=a.text_input("Message ID",value="MANUAL-001"); name=b.text_input("Sender name"); contact=a.text_input("Sender phone or email"); channel=b.selectbox("Channel",["sms","portal","email"]); body=st.text_area("Message",height=130); dob=st.text_input("Date of birth (optional, YYYY-MM-DD)")
        submit=st.form_submit_button("Process safely")
    if submit:
        try:
            out=agent.process({"id":mid,"from_name":name,"from_contact":contact,"channel":channel,"body":body,"stated_dob":dob or None})
            st.session_state.last=out
        except Exception as exc: st.error(f"Input rejected: {type(exc).__name__}")
    if st.session_state.get("last"):
        out=st.session_state.last
        c1,c2,c3=st.columns(3); c1.metric("Urgency",out["urgency"]); c2.metric("Identity", "Verified" if out["verified"] else "Not verified"); c3.metric("Model",out["model_status"])
        st.write("**Intents:**",", ".join(out["intents"])); st.write("**Actions:**",", ".join(out["actions"])); st.write("**Queues:**",", ".join(out["routed_to"]) or "None")
        st.text_area("Reply draft",out["reply_draft"],height=90); st.json(out["trace"])
with tab2:
    sample=ClinicStore().messages; pick=st.selectbox("Sample message",sample,key="sample_pick",format_func=lambda x:f"{x['id']} · {x['from_name']} · {x['body'][:70]}")
    if st.button("Process selected sample"): st.session_state.last=agent.process(pick); st.rerun()
    if st.button("Process all 40 messages"): st.session_state.batch=agent.process_all()
    if st.session_state.get("batch"):
        st.dataframe([{k:r[k] for k in ["id","patient_id","intents","urgency","actions","routed_to"]} for r in st.session_state.batch],use_container_width=True)
with tab3:
    path=Path("evaluation/report_offline.json")
    if path.exists():
        report=json.loads(path.read_text(encoding="utf8")); st.json(report["metrics"]); st.subheader("Missed emergencies"); st.write(report["missed_emergencies"]); st.subheader("must_not violations"); st.json(report["must_not_violations"])
    else: st.info("Run `python -m evaluation.run --offline` to generate the report.")
