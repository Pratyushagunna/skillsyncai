from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel
import spacy
import sqlite3
import os
from dotenv import load_dotenv
from datetime import datetime
import pdfplumber

load_dotenv()

try:
    nlp = spacy.load("en_core_web_lg")
except:
    import spacy.cli
    spacy.cli.download("en_core_web_lg")
    nlp = spacy.load("en_core_web_lg")

def init_db():
    conn = sqlite3.connect('skillsync.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            jd_text TEXT,
            cv_text TEXT,
            score REAL,
            status TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    ''')
    conn.commit()
    return conn

conn = init_db()

class MatchRequest(BaseModel):
    jd_text: str
    cv_text: str

class MatchResult(BaseModel):
    status: str
    score: float
    message: str
    match_id: int

def extract_keywords(text):
    text = text.lower()
    keywords = set()
    for token in nlp(text):
        if token.pos_ in ["NOUN", "PROPN", "ADJ", "VERB"] and not token.is_stop:
            keywords.add(token.lemma_)
    return keywords

def keyword_match_score(jd_text, cv_text):
    jd_keywords = extract_keywords(jd_text)
    cv_keywords = extract_keywords(cv_text)
    if not jd_keywords:
        return 0
    matched = jd_keywords.intersection(cv_keywords)
    return len(matched) / len(jd_keywords)

def extract_skills(text: str) -> set:
    keywords = {"python", "java", "flask", "django", "kotlin", "rest", "api", "rest api", "android", "sql", "aws", "docker", "machine learning", "data science"}
    text = text.lower()
    return {skill for skill in keywords if skill in text}

def calculate_match(jd_text: str, cv_text: str) -> float:
    jd_skills = extract_skills(jd_text)
    cv_skills = extract_skills(cv_text)

    if not jd_skills:
        return 0.0

    match_count = len(jd_skills.intersection(cv_skills))
    score = match_count / len(jd_skills)
    return score

def send_email(to: str, subject: str, body: str):
    print(f"\n=== EMAIL ===\nTo: {to}\nSubject: {subject}\n{body}\n")

app = FastAPI(title="SkillSync AI", version="2.0")

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/match", response_model=MatchResult)
async def match_jd_cv(request: MatchRequest):
    try:
        score = calculate_match(request.jd_text, request.cv_text)
        threshold = float(os.getenv("MATCH_THRESHOLD", 0.5))
        status = "Shortlisted" if score >= threshold else "Rejected"

        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO matches (jd_text, cv_text, score, status) VALUES (?, ?, ?, ?)",
            (request.jd_text, request.cv_text, score, status)
        )
        match_id = cursor.lastrowid
        conn.commit()

        message = "Candidate qualified for interview" if status == "Shortlisted" else "Below threshold score"
        if status == "Shortlisted":
            send_email("candidate@example.com", "Interview Invitation", f"Your application scored {score:.2f} and has been shortlisted!")

        return {
            "status": status,
            "score": score,
            "message": message,
            "match_id": match_id
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/match/pdf", response_model=MatchResult)
async def match_from_pdf(jd_file: UploadFile = File(...), cv_file: UploadFile = File(...)):
    try:
        def extract_text_from_pdf(uploaded_file: UploadFile) -> str:
            with pdfplumber.open(uploaded_file.file) as pdf:
                return "\n".join([page.extract_text() or "" for page in pdf.pages])

        jd_text = extract_text_from_pdf(jd_file)
        cv_text = extract_text_from_pdf(cv_file)

        if not jd_text.strip() or not cv_text.strip():
            raise HTTPException(status_code=400, detail="Could not extract text from one or both files.")

        score = calculate_match(jd_text, cv_text)
        threshold = float(os.getenv("MATCH_THRESHOLD", 0.7))
        status = "Shortlisted" if score >= threshold else "Rejected"

        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO matches (jd_text, cv_text, score, status) VALUES (?, ?, ?, ?)",
            (jd_text, cv_text, score, status)
        )
        match_id = cursor.lastrowid
        conn.commit()

        message = "Candidate qualified for interview" if status == "Shortlisted" else "Below threshold score"
        if status == "Shortlisted":
            send_email("candidate@example.com", "Interview Invitation", f"Your application scored {score:.2f} and has been shortlisted!")

        return {
            "status": status,
            "score": score,
            "message": message,
            "match_id": match_id
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during matching: {str(e)}")

@app.get("/")
async def health_check():
    return {"status": "OK", "message": "SkillSync AI is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
