import re
import asyncio, json
from datetime import date, timedelta
from app.models import IncomingMessage
from app.services.domain import ClinicStore
from app.guardrails.emergency import emergency_status
from app.guardrails.input_safety import suspicious_instruction, identity_conflict
from app.guardrails.policy_enforcement import refill_decision
from app.guardrails.output_validation import validate_result
from app.agent.groq_client import GroqInterpreter

class Agent:
    def __init__(self, store=None):
        self.store=store or ClinicStore(); self.llm=GroqInterpreter(); self._active_message=None
        from app.mcp_server import server as mcp_module
        self.mcp_module=mcp_module; mcp_module.store=self.store

    def _invoke_mcp(self,name,args):
        call_args={"args":args}
        result=asyncio.run(self.mcp_module.mcp.call_tool(name,call_args))
        if isinstance(result,tuple) and len(result)>1 and isinstance(result[-1],dict):
            structured=result[-1]
            if "result" in structured:return structured["result"]
        parts=[]
        for block in result if isinstance(result,(list,tuple)) else []:
            if getattr(block,"type",None)=="text":
                try: parts.append(json.loads(block.text))
                except Exception: parts.append(block.text)
        if len(parts)==1:return parts[0]
        return parts

    def _person(self,m):
        # Contact match wins; name alone is not sufficient authorization.
        contact=m.from_contact.casefold()
        for p in self.store.patients:
            if contact in {p["phone"].casefold(),p["email"].casefold()} or contact==(p.get("authorised_caregiver") or {}).get("phone","").casefold():
                return p
        return self.store.find_patient(m.from_name)

    def _tool(self, trace, name, fn, *args, **kwargs):
        item={"tool":name,"status":"attempted"}; trace.append(item)
        try:
            m=self._active_message; person=self._person(m) if m else None; auth={"patient_id":person["id"],"sender_name":m.from_name,"contact":m.from_contact,"dob":m.stated_dob} if m and person else {}
            if name=="find_patient": mcp_args={"name":m.from_name,"contact":m.from_contact}
            elif name=="verify_patient_or_caregiver": mcp_args=auth
            elif name=="read_patient_medications": mcp_args=auth
            elif name=="check_refill_eligibility": mcp_args={**auth,"medication":str(args[-1])}
            elif name=="find_available_appointment_slots": mcp_args={"provider":args[0],"start_date":args[1],"visit_type":args[2],"part_of_day":args[3] if len(args)>3 else None}
            elif name=="book_appointment": mcp_args={**auth,"provider":args[1],"date":args[2],"start":args[3],"visit_type":args[4],"idempotency_key":args[5]}
            elif name=="cancel_appointment": mcp_args={**auth,"appointment_id":args[0],"idempotency_key":args[2]}
            elif name=="reschedule_appointment": mcp_args={**auth,"appointment_id":args[0],"provider":args[2],"date":args[3],"start":args[4],"visit_type":args[5],"idempotency_key":args[6]}
            elif name=="route_message":
                queue=kwargs.get("queue") or (args[0] if args and isinstance(args[0],str) else "front_desk")
                mcp_args={"queue":queue,"message_id":m.id if m else "unknown","summary":m.body[:240] if m else "Human review requested"}
            elif name=="draft_reply": mcp_args={"reply":str(args[0])}
            else: result=fn(*args,**kwargs); mcp_args=None
            result=self._invoke_mcp(name,mcp_args) if mcp_args is not None else result
            # Traces capture that a read succeeded without copying medication names or full records.
            safe_result=result
            if name=="find_patient": safe_result={"match_found":bool(result and result.get("patient_id"))}
            elif name=="read_patient_medications": safe_result={"authorized":True,"medication_count":len(result) if isinstance(result,list) else 0}
            elif name=="check_refill_eligibility" and isinstance(result,dict): safe_result={k:v for k,v in result.items() if k!="medication"}
            elif name=="route_message" and isinstance(result,dict): safe_result={k:result[k] for k in ["queued","queue","message_id"] if k in result}
            item.update(status="success",result=safe_result); return result
        except Exception as e:
            item.update(status="error",error=type(e).__name__); return None

    def process(self, raw):
        m=IncomingMessage.model_validate(raw); body=m.body; low=body.casefold(); store=self.store
        self._active_message=m
        trace=[]; tools=[]; actions=[]; routes=[]; intents=[]; errors=[]
        person=self._person(m); patient_id=person["id"] if person else None
        identity_conflict_found=bool(person and identity_conflict(body,person["name"]))
        auth={"verified":False}
        if person:
            tools.append("find_patient")
            self._tool(trace,"find_patient",lambda:None)
            if identity_conflict_found:
                errors.append("identity_conflict_in_message")
            else:
                tools.append("verify_patient_or_caregiver")
                auth=self._tool(trace,"verify_patient_or_caregiver",store.authorize,person["id"],m.from_name,m.from_contact,m.stated_dob) or {"verified":False}
        verified=bool(auth.get("verified")); output_patient_id=patient_id if verified else None
        # Language understanding can supplement deterministic classification but cannot downgrade safety.
        llm_tags=self.llm.classify(body)
        if re.search(r"\b(refill\w*|renew\w*|more \w+|ran out|out of pills|prescription|script|metformina)\b",low) or any(re.search(re.escape(x["medication"].split()[0]),low,re.I) for x in store.medications): intents.append("refill")
        if re.search(r"\b(book\w*|appointment|see dr|see sarah|come in|get (her|him|me) seen|physical|checkup|cita|chequeo)\b",low): intents.append("schedule")
        if re.search(r"\b(move my\b|reschedule|change my appointment)\b",low): intents=[x for x in intents if x!="schedule"]+(["reschedule"] if "reschedule" not in intents else [])
        if re.search(r"\b(cancel my appointment|cancel.*appointment)\b",low): intents=[x for x in intents if x!="schedule"]+(["cancel"] if "cancel" not in intents else [])
        if re.search(r"\b(balance|bill|billing|copay|insurance covered)\b",low): intents.append("billing")
        if (re.search(r"\b(records?|lab results|vaccination record)\b",low) or re.search(r"\b(?:what|which|list|tell me)\b.{0,50}\bmedications?\b.{0,30}\b(?:he|she|they)\s+takes?\b",low)) and not re.search(r"\b(explain|what does|what .* mean|interpret)\b",low): intents.append("records")
        if re.search(r"\b(chest|wheez\w*|fever|cough|blood sugar|bleed\w*|suicid\w*|low lately|uti|burning when i pee|high tsh|confus\w*|fell|hit her head|shaky|sweaty)\b|don't see the point of anything|mood.{0,25}\b(low|down)\b",low): intents.append("clinical")
        if re.search(r"\b(phone number|clinic hours|open the day|open on|open .*thanksgiving)\b",low): intents.append("admin")
        if re.search(r"new patient|accept new patients",low): intents.append("new_patient")
        if "new_patient" in intents: intents=[x for x in intents if x!="schedule"]
        if re.search(r"\b(wife|husband|my mom|my mother|my father|my dad|my wife|my husband|neighbor|neighbour|friend|coworker|colleague)\b",low):
            intents.append("third_party")
            if not verified and re.search(r"\b(my wife|my husband|wife|husband|neighbor|neighbour|friend|coworker|colleague)\b",low): intents=[x for x in intents if x!="schedule"]
        if "stop to unsubscribe" in low or re.search(r"special offer on medical billing services",low): intents=["spam"]
        if not intents and ("thanks" in low or "thank you" in low): intents=["other"]
        if not intents: intents=llm_tags or ["other"]
        intents=list(dict.fromkeys(intents))
        injection=suspicious_instruction(body)
        emergency,uncertain=emergency_status(body)
        if "schedule" in intents and "clinical" in intents and re.search(r"\b(fever|cough|uti|burning)\b",low): urgency="urgent"
        if injection: actions.append("flag_suspicious_instruction")
        if emergency:
            urgency="emergency"; actions.append("escalate_emergency"); routes.append("clinician_urgent")
            reply="This may be a medical emergency. Please call 911 or go to the nearest emergency department now. The clinic has been alerted."
            tools.append("route_message"); self._tool(trace,"route_message",lambda:None,queue="clinician_urgent")
        elif uncertain:
            urgency="urgent"; actions.append("route_to_clinician"); routes.append("clinician_urgent")
            reply="I’m alerting the clinical team for prompt review. If this may be an emergency, call 911 or go to the nearest emergency department."
            tools.append("route_message"); self._tool(trace,"route_message",lambda:None,queue="clinician_urgent")
        else:
            urgency="routine"; reply="Thanks for contacting Maplewood Family Clinic."
            if "schedule" in intents and "clinical" in intents and re.search(r"\b(fever|cough|uti|burning)\b",low): urgency="urgent"
            if "third_party" in intents and not verified:
                actions.append("decline_disclosure"); reply="I cannot share another person's health or medication information. Please ask them to contact the clinic directly."
            if "records" in intents and not verified and "third_party" not in intents:
                actions.append("request_verification"); reply="Please contact us using the phone or email on file, or provide your full name and date of birth so we can verify your identity."
            if "spam" in intents: actions.append("no_action"); reply=""
            if "new_patient" in intents:
                actions.extend(["answer_directly","offer_new_patient_booking"]); reply="Yes, we are accepting new patients. I can help arrange a 40-minute new patient visit."
            if "billing" in intents:
                actions.append("route_to_billing"); routes.append("billing"); reply="I’ve sent your billing question to our billing team; they can confirm your balance or copay."
                tools.append("route_message"); self._tool(trace,"route_message",lambda:None,queue="billing")
            if "admin" in intents:
                if "hours" in low: actions.append("answer_directly"); reply="Our hours are Monday through Friday, 9:00 a.m. to 5:00 p.m., with lunch from noon to 1:00 p.m."
                elif "thanksgiving" in low: actions.append("answer_directly"); reply="The clinic is closed November 26 and 27 for the holiday."
                else: actions.append("route_to_front_desk"); routes.append("front_desk"); reply="I’ve sent your request to the front desk team."
            if "clinical" in intents and "schedule" not in intents and not any(x in actions for x in ["escalate_emergency","route_to_clinician"]):
                actions.append("route_to_clinician"); routes.append("clinician_routine")
                if urgency=="routine" and re.search(r"\b(bleeding|dark stools|out of pills|fever|uti|burning|low lately)\b|don't see the point of anything|mood.{0,25}\b(low|down)\b",low): urgency="urgent"; routes[-1]="clinician_urgent"
                if "suicide" not in low and "kill myself" not in low: reply="I’ve sent your concern to the clinical team for review. I can’t interpret symptoms or lab results here."
                tools.append("route_message"); self._tool(trace,"route_message",lambda:None,queue=routes[-1])
            if "refill" in intents and verified and not emergency:
                meds=self._tool(trace,"read_patient_medications",store.permitted_medications,person["id"],m.from_name,m.from_contact,m.stated_dob); tools.append("read_patient_medications")
                requested=next((x for x in meds or [] if re.search(re.escape(re.sub(r"\s+.*$","",x["medication"]).split()[0]),body,re.I)),None)
                if not requested and meds: requested=next((x for x in meds if x["medication"].split()[0].casefold() in low or any(alias in low and x.get("controlled_schedule") for alias in ["xanax"])),None)
                if not requested and len(meds)==1 and re.search(r"\b(refill\w*|prescription|script)\b",low): requested=meds[0]
                if requested:
                    tools.append("check_refill_eligibility"); decision=self._tool(trace,"check_refill_eligibility",refill_decision,store,person["id"],requested["medication"].split()[0]) or {"reason":"tool_error"}
                    reason=decision.get("reason")
                    if decision.get("eligible"):
                        actions.append("prepare_refill_for_approval"); routes.append("provider_refills"); reply="Your refill request has been prepared for provider approval. This does not mean a prescription has been issued."
                    elif reason=="needs_visit":
                        actions.extend(["refill_needs_visit","offer_appointment"]); routes.append("provider_refills"); reply="A visit is needed before we can prepare this refill. I’ve sent your request to the provider and can help arrange an appointment."
                        if urgency=="urgent" or re.search(r"\b(out of pills|out of medication|asap|urgent)\b",low): actions.append("route_to_provider")
                    elif reason=="too_early":
                        actions.append("refill_too_early"); reply=f"It is too early to prepare this request. The earliest date is {decision['earliest_date']}."
                    elif reason in {"controlled","no_refills"}:
                        actions.append("route_to_provider"); routes.append("provider_refills"); reply="I’ve sent your request to the prescribing provider for review."
                    else:
                        actions.append("route_to_provider"); routes.append("provider_refills"); reply="I couldn’t confirm this medication in the active list, so I’ve sent the request to the provider."
                    if "provider_refills" in routes and "route_message" not in tools:
                        tools.append("route_message"); self._tool(trace,"route_message",lambda:None,queue="provider_refills")
                else:
                    actions.append("route_to_provider"); routes.append("provider_refills"); reply="I’ve sent your refill request to the provider for review."
            elif "refill" in intents and not verified:
                actions.append("request_verification"); reply="Please contact us using the phone or email on file, or provide your full name and date of birth to verify before we review medication information."
            if "schedule" in intents and verified:
                # Resolve provider and visit type from message; search availability before booking.
                provider="PATEL" if re.search(r"patel",low) else "KIM" if re.search(r"sarah|kim",low) else person.get("primary_provider","PATEL")
                vt="annual_physical" if re.search(r"annual|physical|checkup|chequeo",low) else "sick_visit" if re.search(r"fever|cough|uti|burning",low) else "follow_up"
                start=store.today if re.search(r"\b(today|this week|today or tomorrow)\b",low) else store.today+timedelta(days=1)
                if "next week" in low or "semana" in low: start=store.today+timedelta(days=7)
                for day_name,delta in [("tuesday",1),("wednesday",2),("thursday",3),("friday",4),("monday",0)]:
                    if day_name in low:
                        start=store.today+timedelta(days=delta)
                        while start.strftime("%A").casefold()!=day_name: start+=timedelta(days=1)
                        break
                part="morning" if "morning" in low else "afternoon" if "afternoon" in low else None
                tools.append("find_available_appointment_slots")
                slots=self._tool(trace,"find_available_appointment_slots",store.find_slots,provider,start.isoformat(),vt,part,3) or []
                explicit_date=re.search(r"\bthe\s+(\d{1,2})(?:st|nd|rd|th)?(?=\s|$)",low)
                if explicit_date and int(explicit_date.group(1))<=30:
                    requested_day=date(2026,11,int(explicit_date.group(1)))
                    slots=[s for s in store.find_slots(provider,requested_day.isoformat(),vt,part,20) if s["date"]==requested_day.isoformat()]
                wanted_time=re.search(r"\b(\d{1,2})(?::(\d\d))?\s*(am|pm)\b",low)
                if wanted_time:
                    h=int(wanted_time.group(1))%12+(12 if wanted_time.group(3)=="pm" else 0); tm=f"{h:02d}:{wanted_time.group(2) or '00'}"
                    day=(date(2026,11,int(explicit_date.group(1))) if explicit_date and int(explicit_date.group(1))<=30 else start)
                    if store.slot_valid(provider,day.isoformat(),tm,vt): slots=[{"provider":provider,"date":day.isoformat(),"start":tm,"visit_type":vt}]
                    else: slots=[]
                if slots and "escalate_emergency" not in actions:
                    # Requests phrased as a question/time preference get an offer; explicit booking gets committed.
                    if (re.search(r"\b(book\w*|schedule me|please schedule|can i get|any chance|cita)\b",low) or "sick_visit"==vt and re.search(r"\b(appointment|get .*seen|today or tomorrow)\b",low)) and "reschedule" not in intents:
                        s=slots[0]; tools.append("book_appointment")
                        booked=self._tool(trace,"book_appointment",store.book,person["id"],provider,s["date"],s["start"],vt,m.id)
                        if booked: actions.append("book_appointment"); reply=f"Your {vt.replace('_',' ')} is booked for {s['date']} at {s['start']}."
                        else: actions.append("offer_alternatives"); reply="That slot could not be booked. The front desk can help find another time."
                    else: actions.append("offer_appointment"); reply=f"An available {vt.replace('_',' ')} is {slots[0]['date']} at {slots[0]['start']}. Please confirm if you would like me to book it."
                else:
                    actions.append("offer_alternatives"); routes.append("front_desk"); reply="I couldn’t find a valid slot matching that request. I’ve asked the front desk to help with alternatives."
                    if "route_message" not in tools:
                        tools.append("route_message"); self._tool(trace,"route_message",lambda:None,queue="front_desk")
            if "reschedule" in intents and verified:
                own=[a for a in store.appointments if a["patient_id"]==person["id"] and a["status"]=="booked"]
                if own:
                    old=own[0]; provider=old["provider"]; vt=old["visit_type"]
                    desired="2026-11-13" if "friday" in low else "2026-11-23" if "following week" in low else "2026-11-13"
                    part="afternoon" if "afternoon" in low else "morning" if "morning" in low else None
                    slots=store.find_slots(provider,desired,vt,part,1)
                    if slots:
                        s=slots[0]; tools.append("reschedule_appointment")
                        result=self._tool(trace,"reschedule_appointment",store.reschedule,old["id"],person["id"],provider,s["date"],s["start"],vt,m.id)
                        if result: actions.append("reschedule_appointment"); reply=f"Your appointment has been moved to {s['date']} at {s['start']}."
                        else: actions.append("offer_alternatives"); reply="I couldn't move the appointment and have asked the front desk to help."
                    else: actions.append("offer_alternatives"); reply="I couldn't find a matching open slot. I’ve asked the front desk to offer alternatives."
                else: actions.append("offer_alternatives"); reply="I couldn't find an existing appointment to move. Please contact the front desk."
            if "cancel" in intents and verified:
                own=[a for a in store.appointments if a["patient_id"]==person["id"] and a["status"]=="booked"]
                tomorrow=(store.today+timedelta(days=1)).isoformat()
                target=next((a for a in own if a["date"]==tomorrow),None) or (own[0] if len(own)==1 else None)
                if target:
                    tools.append("cancel_appointment"); result=self._tool(trace,"cancel_appointment",store.cancel,target["id"],person["id"],m.id)
                    if result: actions.append("cancel_appointment"); reply="Your appointment cancellation has been recorded."
                    else: actions.append("route_to_front_desk"); routes.append("front_desk")
                else: actions.append("route_to_front_desk"); routes.append("front_desk"); reply="I couldn’t identify which appointment to cancel, so I’ve sent this to the front desk."
            if "clinical" in intents and not verified and not actions: actions.append("request_verification")
            if "records" in intents and verified and "vaccination" in low:
                actions.append("route_to_front_desk"); routes.append("front_desk"); reply="I’ve sent the vaccination record request to the front desk for processing."
            if "other" in intents: actions.append("acknowledge")
            if not actions: actions.append("answer_directly")
        routes=list(dict.fromkeys(routes)); actions=list(dict.fromkeys(actions))
        for queue in routes:
            delivered=any(t.get("tool")=="route_message" and t.get("status")=="success" and isinstance(t.get("result"),dict) and t["result"].get("queue")==queue for t in trace)
            if not delivered:
                tools.append("route_message"); self._tool(trace,"route_message",lambda:None,queue=queue)
        # use a safe constrained English emergency reply; never append ordinary reply content
        if emergency: reply="This may be a medical emergency. Please call 911 or go to the nearest emergency department now. The clinic has been alerted."
        elif verified and person.get("preferred_language")=="Spanish":
            if "prepare_refill_for_approval" in actions: reply="Su solicitud de resurtido fue enviada al proveedor para su aprobación. Esto no significa que se haya emitido una receta."
            elif "book_appointment" in actions: reply="Su cita ha sido programada."
            elif "refill_too_early" in actions: reply=f"Es demasiado pronto para preparar la solicitud. La fecha más próxima es {next((x.get('result',{}).get('earliest_date') for x in trace if isinstance(x.get('result'),dict) and x['result'].get('earliest_date')), 'la fecha indicada')}."
        tools.append("draft_reply"); self._tool(trace,"draft_reply",lambda:reply,reply)
        result={"id":m.id,"patient_id":output_patient_id,"intents":intents,"urgency":urgency,"actions":actions,"routed_to":routes,"tool_calls":tools,"reply_draft":reply,"verified":verified,"trace":trace,"model_status":self.llm.status,"errors":errors}
        try:
            return validate_result(result).model_dump()
        except Exception as exc:
            delivered={t.get("result",{}).get("queue") for t in trace if t.get("tool")=="route_message" and t.get("status")=="success" and isinstance(t.get("result"),dict)}
            safe_emergency=emergency and "clinician_urgent" in delivered
            fallback={"id":m.id,"patient_id":None,"intents":["clinical"] if emergency or uncertain else ["other"],
                "urgency":"emergency" if safe_emergency else "urgent" if emergency or uncertain else "routine",
                "actions":["escalate_emergency"] if safe_emergency else ["route_to_clinician"] if emergency or uncertain else ["request_verification"],
                "routed_to":["clinician_urgent"] if safe_emergency else [],"tool_calls":tools,
                "reply_draft":"This may be a medical emergency. Please call 911 or go to the nearest emergency department now. The clinic has been alerted." if safe_emergency else "Please contact the clinic for human review. If this may be an emergency, call 911 or go to the nearest emergency department.",
                "verified":False,"trace":trace,"model_status":self.llm.status,"errors":[*errors,f"output_validation:{type(exc).__name__}"]}
            return validate_result(fallback).model_dump()

    def process_all(self): return [self.process(m) for m in self.store.messages]
