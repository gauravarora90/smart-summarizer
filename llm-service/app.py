# app.py  (replace your existing file with this content)
import os
import io
import json
import time
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Body
from pydantic import BaseModel
import openai

# PDF reader
from pypdf import PdfReader

app = FastAPI()

MODE = os.getenv("MODE", "mock")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")

if MODE == "real" and not OPENAI_KEY:
    raise RuntimeError("MODE=real requires OPENAI_API_KEY")

if OPENAI_KEY:
    openai.api_key = OPENAI_KEY

# Configurable chunking params via env
CHUNK_MAX_CHARS = int(os.getenv("CHUNK_MAX_CHARS", "3000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")

class SummReq(BaseModel):
    text: str
    style: str = "medium"

# -----------------------
# Utilities
# -----------------------
def chunk_text(text: str, max_chars: int = CHUNK_MAX_CHARS, overlap: int = CHUNK_OVERLAP) -> List[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    L = len(text)
    while start < L:
        end = min(start + max_chars, L)
        chunks.append(text[start:end])
        if end == L:
            break
        start = max(0, end - overlap)
    return chunks

def extract_text_from_bytes(content: bytes, filename: str) -> str:
    fn = filename.lower()
    if fn.endswith(".pdf"):
        try:
            reader = PdfReader(io.BytesIO(content))
            parts = []
            for page in reader.pages:
                txt = page.extract_text()
                if txt:
                    parts.append(txt)
            return "\n".join(parts)
        except Exception:
            return ""
    else:
        # try plain text decode
        try:
            return content.decode("utf-8")
        except Exception:
            # fallback empty
            return ""

def safe_parse_json_from_model(s: str) -> Dict[str, Any]:
    # try to extract first {...} object
    try:
        start = s.index("{")
        end = s.rindex("}") + 1
        raw = s[start:end]
        parsed = json.loads(raw)
        return parsed
    except Exception:
        # fallback: wrap raw text into fields
        txt = s.strip()
        return {
            "short": txt[:140],
            "medium": txt[:800],
            "long": txt[:2000],
            "highlights": [txt[:120]] if txt else [],
            "confidence": 0.5
        }

# -----------------------
# OpenAI / mock wrappers
# -----------------------
def call_openai_for_summary(text: str) -> Dict[str, Any]:
    """
    Single-chunk summarization call wrapper.
    Respects MODE=mock (deterministic) if OPENAI key missing or MODE!=real.
    """
    if MODE != "real" or not OPENAI_KEY:
        # deterministic mock
        return {
            "short": (text[:120] + "...") if len(text) > 120 else text,
            "medium": (text[:400] + "...") if len(text) > 400 else text,
            "long": (text[:800] + "...") if len(text) > 800 else text,
            "highlights": [ (text[:100] + "...") ] if text else [],
            "confidence": 0.7
        }

    prompt = f"""
You are a concise summarizer. Produce JSON ONLY with these exact keys:
{{"short":"...", "medium":"...", "long":"...", "highlights":["...","..."], "confidence":0.0 }}

Requirements:
- short: 1-2 sentence summary (<=30 words).
- medium: 3-6 sentence summary (concise).
- long: a more detailed summary.
- highlights: list 3-6 short bullet points.
- confidence: decimal 0..1.

TEXT:
\"\"\"{text}
\"\"\"
"""
    try:
        resp = openai.ChatCompletion.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful summarization assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=1200,
        )
        reply = resp.choices[0].message["content"]
        parsed = safe_parse_json_from_model(reply)
        return parsed
    except Exception as e:
        # on error, raise to caller to handle / retry
        raise

def aggregate_chunk_summaries(chunk_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Combine multiple chunk JSON summaries into a single final summary.
    If running in mock, do a deterministic combine; otherwise ask the model to combine.
    """
    if not chunk_summaries:
        return {"short":"", "medium":"", "long":"", "highlights":[], "confidence":0.0}

    if MODE != "real" or not OPENAI_KEY:
        # simple deterministic aggregation for mock
        medium_join = " ".join([c.get("medium","") for c in chunk_summaries])
        highlights = []
        for c in chunk_summaries:
            highlights.extend(c.get("highlights",[]))
        # dedupe while preserving order
        seen = set()
        dedup = []
        for h in highlights:
            if h not in seen:
                dedup.append(h); seen.add(h)
        avg_conf = round(sum([c.get("confidence",0.7) for c in chunk_summaries]) / len(chunk_summaries), 2)
        return {
            "short": medium_join[:140] + ("..." if len(medium_join) > 140 else ""),
            "medium": medium_join[:800] + ("..." if len(medium_join) > 800 else ""),
            "long": medium_join[:2000] + ("..." if len(medium_join) > 2000 else ""),
            "highlights": dedup[:5],
            "confidence": avg_conf
        }

    # Real-mode: ask OpenAI to combine the chunk summaries
    payload = {"chunks": chunk_summaries}
    agg_prompt = f"""
You are a summarization combiner. You receive a JSON object with a "chunks" array where each element is:
{{"short":"...", "medium":"...", "long":"...", "highlights":[...], "confidence":0.0}}

Task: Merge them into ONE JSON with the same keys:
{{"short":"...", "medium":"...", "long":"...", "highlights":[...], "confidence":0.0}}

Guidelines:
- short: produce a single 1-2 sentence summary covering the whole document.
- medium: merge important points from chunk 'medium' fields.
- long: synthesize long fields into a coherent detailed summary.
- highlights: select top 5 highlights across chunks, deduplicate.
- confidence: average chunk confidences.

Output JSON ONLY, no explanation.

Here is the chunks JSON:
{json.dumps(payload, ensure_ascii=False)}
"""
    try:
        resp = openai.ChatCompletion.create(
            model=OPENAI_MODEL,
            messages=[
                {"role":"system", "content":"You are a summarization combiner."},
                {"role":"user", "content": agg_prompt}
            ],
            temperature=0.2,
            max_tokens=1500
        )
        reply = resp.choices[0].message["content"]
        parsed = safe_parse_json_from_model(reply)
        return parsed
    except Exception:
        # fallback deterministic
        medium_join = " ".join([c.get("medium","") for c in chunk_summaries])
        highlights = []
        for c in chunk_summaries:
            highlights.extend(c.get("highlights",[]))
        seen = set()
        dedup = []
        for h in highlights:
            if h not in seen:
                dedup.append(h); seen.add(h)
        avg_conf = round(sum([c.get("confidence",0.7) for c in chunk_summaries]) / len(chunk_summaries), 2)
        return {
            "short": medium_join[:140] + ("..." if len(medium_join) > 140 else ""),
            "medium": medium_join[:800] + ("..." if len(medium_join) > 800 else ""),
            "long": medium_join[:2000] + ("..." if len(medium_join) > 2000 else ""),
            "highlights": dedup[:5],
            "confidence": avg_conf
        }

# -----------------------
# Endpoints
# -----------------------

@app.get("/health")
async def health():
    return {"status":"ok", "mode": MODE}

@app.post("/api/summarize")
async def summarize(payload: SummReq):
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    # If small text -> single call
    if len(text) <= CHUNK_MAX_CHARS:
        try:
            single = call_openai_for_summary(text)
            return single
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"openai error: {str(e)}")

    # else chunk it
    chunks = chunk_text(text)
    chunk_summaries = []
    for ch in chunks:
        try:
            s = call_openai_for_summary(ch)
        except Exception:
            # retry once after small sleep
            time.sleep(1)
            try:
                s = call_openai_for_summary(ch)
            except Exception as e:
                # on repeated failure, fallback to mock-like summary for this chunk
                s = {
                    "short": ch[:120],
                    "medium": ch[:400],
                    "long": ch[:800],
                    "highlights": [ch[:100]],
                    "confidence": 0.5
                }
        chunk_summaries.append(s)

    aggregated = aggregate_chunk_summaries(chunk_summaries)
    return aggregated

@app.post("/api/summarize-file")
async def summarize_file(file: UploadFile = File(...)):
    if not file:
        raise HTTPException(status_code=400, detail="file is required")
    content = await file.read()
    text = extract_text_from_bytes(content, file.filename)
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="no extractable text from file")
    # reuse summarize logic by calling internal function pattern
    # if small -> single; else chunk -> aggregate
    if len(text) <= CHUNK_MAX_CHARS:
        try:
            single = call_openai_for_summary(text)
            return single
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"openai error: {str(e)}")

    chunks = chunk_text(text)
    chunk_summaries = []
    for ch in chunks:
        try:
            s = call_openai_for_summary(ch)
        except Exception:
            time.sleep(1)
            try:
                s = call_openai_for_summary(ch)
            except Exception:
                s = {
                    "short": ch[:120],
                    "medium": ch[:400],
                    "long": ch[:800],
                    "highlights": [ch[:100]],
                    "confidence": 0.5
                }
        chunk_summaries.append(s)

    aggregated = aggregate_chunk_summaries(chunk_summaries)
    return aggregated
