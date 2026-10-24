from fastapi import FastAPI, HTTPException
from app.agent.processor import Agent
from app.services.domain import ClinicStore
from app.models import IncomingMessage

store=ClinicStore(); agent=Agent(store)
app=FastAPI(title="Healthcare AI Front Desk Agent",version="1.0.0")

@app.get("/health")
def health(): return {"status":"ok","model_status":agent.llm.status,"synthetic_data":True}

@app.post("/process")
def process_message(message: IncomingMessage):
    try:return agent.process(message.model_dump())
    except Exception as exc: raise HTTPException(422,detail=type(exc).__name__)

@app.post("/batch")
def batch(): return agent.process_all()

@app.get("/evaluation")
def evaluation():
    import json
    from pathlib import Path
    path=Path("evaluation/report_offline.json")
    if not path.exists(): raise HTTPException(404,"Run python -m evaluation.run --offline first")
    result=json.loads(path.read_text(encoding="utf8")); result.pop("predictions",None); return result
