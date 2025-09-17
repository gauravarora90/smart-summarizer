import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import openai

app = FastAPI()

MODE = os.getenv("MODE", "mock")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")

if MODE == "real" and not OPENAI_KEY:
    raise RuntimeError("MODE=real requires OPENAI_API_KEY")

if OPENAI_KEY:
    openai.api_key = OPENAI_KEY

class SummReq(BaseModel):
    text: str
    style: str = "medium"

@app.post("/api/summarize")
async def summarize(payload: SummReq):
    text = payload.text or ""
    if MODE == "mock":
        return {
            "short": text[:120],
            "medium": text[:400],
            "long": text[:800],
            "highlights": [text[:120]],
            "confidence": 0.6
        }

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful summarization assistant."},
                {"role": "user", "content": f"Summarize this text:\n\n{text}"}
            ],
            max_tokens=200,
            temperature=0.2,
        )
        ans = resp.choices[0].message["content"].strip()
        return {
            "short": ans,
            "medium": ans,
            "long": ans,
            "highlights": [ans],
            "confidence": 0.9
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "ok", "mode": MODE}
