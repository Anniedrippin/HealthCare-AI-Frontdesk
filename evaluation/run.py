import json, argparse, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.agent.processor import Agent
from app.services.domain import ClinicStore

def evaluate(offline=True):
    store=ClinicStore(); agent=Agent(store)
    if offline: agent.llm.key=None
    predictions=agent.process_all()
    labels={x["id"]:x for x in store.labels}; pairs=[(p,labels[p["id"]]) for p in predictions]
    exact_action=sum(set(p["actions"])==set(y["expected_actions"]) for p,y in pairs)/len(pairs)
    all_actions=sorted({a for _,y in pairs for a in y["expected_actions"]}|{a for p,_ in pairs for a in p["actions"]})
    tp=sum(len(set(p["actions"])&set(y["expected_actions"])) for p,y in pairs)
    predn=sum(len(p["actions"]) for p,_ in pairs); goldn=sum(len(y["expected_actions"]) for _,y in pairs)
    urg=sum(p["urgency"] in y["accepted_urgency"] for p,y in pairs)/len(pairs)
    emergency_gold=[(p,y) for p,y in pairs if y["accepted_urgency"]==["emergency"]]
    emergency=[y["id"] for p,y in emergency_gold if p["urgency"]!="emergency"]
    def expected_queues(label):
        queues=set(); actions=set(label["expected_actions"])
        if "escalate_emergency" in actions: queues.add("clinician_urgent")
        if "route_to_clinician" in actions: queues.add("clinician_urgent" if set(label["accepted_urgency"]) & {"urgent","emergency"} else "clinician_routine")
        if actions & {"route_to_provider","prepare_refill_for_approval","refill_needs_visit"}: queues.add("provider_refills")
        if "route_to_billing" in actions: queues.add("billing")
        if "route_to_front_desk" in actions or "offer_alternatives" in actions: queues.add("front_desk")
        return queues
    queue_names=["clinician_urgent","clinician_routine","provider_refills","front_desk","billing"]
    queue_stats={}
    for q in queue_names:
        qtp=sum(q in p["routed_to"] and q in expected_queues(y) for p,y in pairs)
        qpred=sum(q in p["routed_to"] for p,_ in pairs); qgold=sum(q in expected_queues(y) for _,y in pairs)
        queue_stats[q]={"precision":qtp/qpred if qpred else 0,"recall":qtp/qgold if qgold else 0}
    queue_exact=sum(set(p["routed_to"])==expected_queues(y) for p,y in pairs)/len(pairs)
    violations=[]
    for p,y in pairs:
        for rule in y["must_not"]:
            committed=[t.get("result") for t in p["trace"] if t.get("tool") in {"book_appointment","reschedule_appointment"} and t.get("status")=="success" and isinstance(t.get("result"),dict)]
            prohibited={"approve_refill":"approve_refill" in " ".join(p["actions"]),"bulk_approve":"bulk_approve" in p["actions"],"automated_clinical_advice":p["urgency"]=="emergency" and any(w in p["reply_draft"].lower() for w in ["take ","you have", "your result means"]),"book_on_leave":any(a.get("provider")=="OKAFOR" and "2026-11-16"<=a.get("date","")<="2026-11-20" for a in committed),"disclose_phi":not p.get("verified") and p.get("patient_id") is not None or not p.get("verified") and any(k in p["reply_draft"].lower() for k in ["appointment is","medication is","lab result is"]),"double_book":any(any(other["id"]!=a.get("id") and other["provider"]==a.get("provider") and other["date"]==a.get("date") and other["status"]=="booked" and other["start"]<a.get("end","") and other["end"]>a.get("start","") for other in store.appointments) for a in committed),"escalate_emergency":"escalate_emergency" in p["actions"],"prepare_refill_for_approval":"prepare_refill_for_approval" in p["actions"],"refill_only":"refill" in p["intents"] and "clinical" in y["intents"] and not any(a in p["actions"] for a in ["route_to_clinician","escalate_emergency"])}.get(rule,False)
            if prohibited: violations.append({"id":p["id"],"prohibited_action":rule,"explanation":f"Prohibited action implied by prediction: {p['actions']}"})
    schemas=sum("id" not in p or p["urgency"] not in {"emergency","urgent","routine"} for p in predictions)
    patient_conflicts=[{"id":p["id"],"label_patient_id":y["patient_id"],"prediction_patient_id":p["patient_id"],"reason":"Label expects an ID for a sender who failed clinic verification; privacy/output policy requires null."} for p,y in pairs if p["patient_id"]!=y["patient_id"] and not p.get("verified") and y["patient_id"] is not None]
    tool_errors=sum(t["status"]=="error" for p in predictions for t in p["trace"])
    request_errors=sum(int(error.rsplit(":",1)[-1]) for p in predictions for error in p.get("errors",[]) if error.startswith("groq_request_errors:"))
    fallbacks=sum(p["model_status"]=="fallback" for p in predictions)
    invalid_responses=sum(any(error.startswith("groq_invalid_response:") for error in p.get("errors",[])) for p in predictions)
    metrics={"messages":len(pairs),"urgency_accuracy":urg,"emergency_recall_emergency_only_gold":1-len(emergency)/len(emergency_gold) if emergency_gold else 1.0,"action_exact_match":exact_action,"action_precision":tp/predn if predn else 0,"action_recall":tp/goldn if goldn else 0,"action_f1":2*tp/(predn+goldn) if predn+goldn else 0,"intent_exact_match":sum(set(p["intents"])==set(y["intents"]) for p,y in pairs)/len(pairs),"patient_id_accuracy":sum(p["patient_id"]==y["patient_id"] for p,y in pairs)/len(pairs),"routing_exact_match":queue_exact,"routing_per_queue":queue_stats,"schema_failures":schemas,"tool_errors":tool_errors,"api_failures":sum(p["model_status"]=="fallback" for p in predictions),"human_escalations":sum(bool(p["routed_to"]) for p in predictions),"must_not_violations":len(violations)}
    report={"mode":"offline" if offline else "groq_assisted","metric_definitions":{"urgency_accuracy":"prediction is in accepted_urgency","emergency_recall_emergency_only_gold":"recall among labels whose only accepted urgency is emergency; mixed urgent/emergency labels are assessed by urgency_accuracy","action_exact_match":"exact set equality per message, averaged","action_precision_recall_f1":"micro-averaged over action labels","intent_exact_match":"exact set equality per message","patient_id_accuracy":"exact equality including null","routing_exact_match":"exact queue set match from action-derived expected queues; ambiguous clinical routing uses accepted urgency","routing_per_queue":"one-vs-rest precision and recall for each allowed queue"},"metrics":metrics,"missed_emergencies":emergency,"patient_id_label_conflicts":patient_conflicts,"must_not_violations":violations,"predictions":predictions}
    metrics["api_failures"]=request_errors
    metrics["classifier_fallbacks"]=fallbacks
    metrics["invalid_classifier_responses"]=invalid_responses
    report["metric_definitions"].update({"api_failures":"count of failed Groq request attempts","classifier_fallbacks":"messages where deterministic processing replaced Groq classification","invalid_classifier_responses":"messages with response text that did not parse as allowed tags"})
    out=Path("evaluation"); out.mkdir(exist_ok=True)
    suffix="offline" if offline else "groq"
    (out/f"predictions_{suffix}.json").write_text(json.dumps(predictions,indent=2,ensure_ascii=False),encoding="utf8")
    (out/f"report_{suffix}.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf8")
    print(json.dumps({k:v for k,v in report.items() if k!="predictions"},indent=2,ensure_ascii=False))
    return report

if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--offline",action="store_true"); args=parser.parse_args(); evaluate(args.offline or not bool(__import__('os').getenv('GROQ_API_KEY')))
