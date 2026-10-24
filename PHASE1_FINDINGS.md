# Phase 1: source findings and policy-to-test matrix

## Specification

The supplied three-page take-home asks for one output per inbox message, an MCP tool server over the clinic data, and a reproducible evaluation including missed emergencies and every `must_not` violation. Safety outranks presentation polish. The user-provided project constraints add FastAPI, Streamlit, Python 3.11+, Pydantic, pytest, Groq with offline fallback, no external publication, and date 2026-11-09.

## Inspected source schemas

- `clinic.json`: clinic clock/timezone, weekday hours, lunch, holidays, three providers and leave, visit durations, booking constraints, refill policy, emergency response policy, privacy verification rule, routing queue allowlist.
- `patients.json`: 25 patient records with ID, name, DOB, phone/email, primary provider, last visit, allergies, language, optional one authorized caregiver `{name, relationship, phone}`.
- `medications.json`: 21 records keyed by patient ID with medication, optional controlled schedule, supply duration, last fill, remaining refills, prescriber.
- `appointments.json`: 170 bookings with ID, patient, provider, date, start/end, visit type, status.
- `messages_sample.json`: 40 messages with ID, timestamp, channel, sender name/contact, body; optional `stated_dob`.
- `labels_sample.json`: 40 records with `id`, `patient_id`, `intents`, `accepted_urgency`, `expected_actions`, `must_not`, and explanatory `trap`. Urgency is an accepted set; action and intent fields are expected sets in evaluation. There are 12 distinct intent labels and nine `must_not` labels.

## Source policies (not inferred)

- Local date is 2026-11-09; clinic timezone America/Chicago. Hours Mon-Fri 09:00-17:00, lunch 12:00-13:00. Holidays: 2026-11-26, 2026-11-27, 2026-12-25.
- Slots start at :00, :20, or :40. No lunch/holiday/provider-leave bookings; no overlapping provider appointments. Sick visits should be offered within one business day where possible. Durations: new patient 40m, annual physical 40m, follow-up 20m, sick visit 20m, telehealth 20m.
- Refill may only be prepared for provider approval, never approved/sent. Eligibility requires active medication, not controlled, last visit within 12 months, remaining refills > 0, and request no earlier than seven days before supply end (`last_filled + days_supply`). Controlled medications always go to prescriber. If overdue for visit, do not prepare; offer appointment and route provider. Zero refills route provider for new prescription. Early requests get earliest eligible date.
- Any message that may describe a medical emergency is escalated immediately to a human. Never give automated clinical advice in that case. Reply may only advise 911 or nearest emergency department and say clinic has been alerted.
- Health/appointment details can only be disclosed to verified patient or authorized caregiver. Verification is exact name + DOB match OR sender contact matching patient/caregiver contact on file. A name alone is not verification.
- Queues: clinician_urgent, clinician_routine, provider_refills, front_desk, billing.
- Action vocabulary: `escalate_emergency`, `route_to_clinician`, `route_to_provider`, `route_to_billing`, `route_to_front_desk`, `prepare_refill_for_approval`, `refill_needs_visit`, `refill_too_early`, `book_appointment`, `reschedule_appointment`, `cancel_appointment`, `offer_appointment`, `offer_alternatives`, `offer_new_patient_booking`, `request_verification`, `decline_disclosure`, `flag_suspicious_instruction`, `answer_directly`, `acknowledge`, `no_action`.

## Policy-to-test matrix

| Policy / trust boundary | Enforced in | Required tests |
|---|---|---|
| Emergency outranks all administrative intents; constrained reply | emergency guardrail + agent | chest pain, head injury/confusion, bleeding, respiratory distress, severe hypoglycemia; negated symptoms, idioms, mixed refill/clinical; reply contains only permitted guidance |
| Exact identity or authorized caregiver verification | domain service/tool authorization | matching contact; name+DOB; wrong DOB/new contact; caregiver matching contact; third party denied; patient ID null when unverified |
| No PHI disclosure in reads/replies/traces | authorized read tools + output validation | records request from unverified sender; spouse/third-party appointment inquiry; trace excludes protected values |
| Refill policy | policy service + refill MCP tool | active/inactive; 12-month boundary; controlled; no refills; 7-day boundary/early date; approval-only wording |
| Slot policy and concurrency | scheduler service + booking MCP tools | durations, slot increments, lunch, hours, holidays, leave, existing overlaps, same-slot concurrent/double booking, reschedule/cancel ownership and existence |
| Prompt injection is untrusted | input guardrail + fixed policy/tool schemas | malicious instructions embedded in valid refill, bulk approval request, arbitrary disclosure/tool request |
| Tool execution and trace accuracy | service facade + result schema | successes, validation denial, duplicate idempotency, operation failure and accurately recorded trace |
| Output vocabulary and claims | output guardrail | invalid action/queue/urgency, unverified patient ID, emergency clinical advice, unsupported successful action claim |
| LLM availability | Groq adapter + deterministic fallback | absent key, malformed response, timeout, rate limit, bounded retry, offline result validity |
| Labels and evaluation | evaluation runner | all 40 predictions; accepted urgency; set precision/recall; each individual `must_not`; missed emergency list; schema/tool/API/escalation counts |

## Implementation plan

1. Build validated data/domain services and deterministic safety-critical policies.
2. Expose narrow, typed tools through the official MCP Python SDK, with traceable operation results and run-scoped appointment state.
3. Add separate input, emergency, policy, authorization, and output guardrails; use Groq only for supplemental language interpretation, with a deterministic fallback.
4. Run all 40 labels, repair generalizable failures, and add regression/adversarial tests.
5. Add FastAPI and Streamlit over the shared service, then document local setup, evaluation, results, limitations, and synthetic-data scope.

No reference label or message ID is used as a production decision rule. The six source JSON files are copied into `data/` unchanged for local reproducibility.
