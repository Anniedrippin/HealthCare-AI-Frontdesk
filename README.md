# Healthcare AI Front Desk

Synthetic-data take-home prototype for Maplewood Family Clinic. It is not clinically validated and is not production-ready.

## Architecture

FastAPI and Streamlit call the same Pydantic-validated `Agent` and `ClinicStore`. JSON is the source of truth; appointment updates exist only in process memory. The official MCP Python SDK server exposes narrow operations in `app/mcp_server/server.py`. Deterministic Python enforces authorization, emergencies, scheduling, and refill policy. Groq is optional and restricted to supplemental intent interpretation; absent keys, rate limits, timeouts, or malformed output fall back to deterministic logic.

The guardrails are separated under `app/guardrails/`: input safety, emergency screening, policy enforcement, tool authorization, and output validation. An emergency short-circuits normal work and receives the clinic's constrained 911/ED plus clinic-alert reply. Reads verify phone/email/caregiver contact or exact patient name plus DOB. Tool traces retain operation names and status but avoid patient records.

## Tools and reused components

MCP tools include patient search, verification, authorized medication read, refill eligibility, slot search, booking, cancellation, rescheduling, routing, and reply drafting. FastAPI, Streamlit, Pydantic, pytest, Groq's official client, and the official `mcp` Python SDK are reused dependencies. Domain policies, agent orchestration, evaluation, test fixtures, and interfaces were built for this project.

## Model and cost

Default model: `openai/gpt-oss-20b`, configurable with `GROQ_MODEL`. GPT-OSS 20B is the documented replacement and appears in the free-plan rate-limit table. Groq lists $0.075/1M input tokens and $0.30/1M output tokens for paid use. At the estimated 3,000–6,000 input and 1,000–2,000 output tokens for 40 short classification requests, that is approximately $0.0005–$0.0011 outside free limits. Offline mode needs no API key and is the reproducible fallback.

## Setup (Windows PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Run tests and both evaluation modes:

```powershell
python -m pytest -q
python -m evaluation.run --offline
python -m evaluation.run
```

Run the API and UI in separate terminals:

```powershell
uvicorn app.api.main:app --reload
streamlit run app/ui/streamlit_app.py
```

The MCP server uses the stdio transport and is normally started by an MCP client, which sends it JSON-RPC messages. Running `python -m scripts.check_mcp` directly in an interactive terminal is not a health check: terminal input such as an empty line is not a valid MCP message. To verify the real client/server handshake and list the registered tools, run:

```powershell
python -m scripts.check_mcp
```

Evaluation writes `evaluation/predictions_offline.json` and `evaluation/report_offline.json`; Groq results use the `_groq` suffix. The report includes metric definitions, missed emergencies, and each `must_not` violation. The exported Groq CSV contains one row per input message with the predicted `id`, `patient_id`, `intents`, `urgency`, `actions`, and `routed_to`.

## Results

Both evaluations below use the same 40-message synthetic sample. These are results on a small, fixed take-home dataset—not evidence of clinical validity or generalization to real patient conversations.

| Metric                         |  Offline evaluation |     Groq evaluation |
| ------------------------------ | ------------------: | ------------------: |
| Messages evaluated             |                  40 |                  40 |
| Urgency accuracy               |                100% |                100% |
| Emergency-only-label recall    |                100% |                100% |
| Action exact match             |                100% |                100% |
| Action precision (micro)       |                100% |                100% |
| Action recall (micro)          |                100% |                100% |
| Action F1 (micro)              |                100% |                100% |
| Intent exact match             |                100% |                100% |
| Patient ID accuracy            |                 95% |                 95% |
| Routing exact match            |                100% |                100% |
| Per-queue precision and recall | 100% for all queues | 100% for all queues |
| Schema failures                |                   0 |                   0 |
| Tool errors                    |                   0 |                   0 |
| API failures                   |        Not reported |                   0 |
| Missed emergencies             |                   0 |                   0 |
| `must_not` violations          |                   0 |                   0 |
| Human escalations              |                  23 |                  23 |

### Groq run: exported message distribution

The supplied Groq CSV contains 40 processed messages. Its predicted urgency distribution is 32 routine, 3 urgent, and 5 emergency. The export shows 23 human escalations in the evaluation report. These counts describe this sample and should not be interpreted as expected real-world clinic rates.

Routing metrics were 100% precision and recall for each queue: `clinician_urgent`, `clinician_routine`, `provider_refills`, `front_desk`, and `billing`.

### Metric definitions and interpretation

- **Urgency accuracy:** accepted-set urgency accuracy against the labels.
- **Emergency-only-label recall:** recall for messages whose gold label is emergency; mixed urgent/emergency labels use the evaluation's urgency-acceptance rule.
- **Action metrics:** exact per-message action match plus micro-averaged action precision, recall, and F1.
- **Intent exact match:** the predicted intent set must match the labelled intent set for that message.
- **Routing exact match:** action-derived exact routing match; per-queue metrics use one-vs-rest precision and recall.
- **Patient ID accuracy:** exact patient ID match. The two known label disagreements are M011 and M027: the labels expect IDs for unverified senders, while the privacy and output rules require `null` unless identity is verified. The implementation honors the privacy rule; both disagreements are reported in `patient_id_label_conflicts`.

The Groq run reported no missed emergencies, no `must_not` violations, no schema failures, no tool errors, and no API failures. These are encouraging regression-test results, but a 40-message sample is too small to establish robust safety or reliability. In particular, zero observed safety violations does not prove that the system is safe.

The full test suite previously passed 21 tests; rerun `python -m pytest -q` in the current environment before relying on that status.

## Limits and next week

The lightweight clinical detector is conservative but is not a validated triage model. Language support is limited; Spanish replies need fuller localization. Schedule language parsing covers common explicit requests, not general natural language. This prototype does not connect to real EHR, SMS, portal, billing, or identity providers. Before real patient data: security/privacy/regulatory assessment, encryption, authenticated role-based access, audit retention, safe production deployment, robust monitoring, tested human escalation operations, localization, threat modeling, and clinical validation are required. No external publication, upload, or GitHub push was performed.
