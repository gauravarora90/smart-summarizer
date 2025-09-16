# simple FastAPI mock summarizer - Day-1
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class SummReq(BaseModel):
    text: str
    style: str = "medium"

@app.post("/api/summarize")
async def summarize(payload: SummReq):
    text = payload.text or ""
    # very small mock: return prefixes
    short = (text[:120] + "...") if len(text) > 120 else text
    medium = (text[:400] + "...") if len(text) > 400 else text
    long = (text[:1000] + "...") if len(text) > 1000 else text
    return {
        "short": short,
        "medium": medium,
        "long": long,
        "highlights": [short],
        "confidence": 0.6
    }

@app.get("/health")
async def health():
    return {"status":"ok"}
