import os
import json
from typing import List
from fastapi import FastAPI, Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, String, Text, Boolean, BigInteger
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from pydantic import BaseModel
from openai import AsyncOpenAI

# ---------------- Database Setup ----------------
SQLALCHEMY_DATABASE_URL = "sqlite:///./agentforge.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class AgentDB(Base):
    __tablename__ = "agents"
    id = Column(String, primary_key=True, index=True)
    name = Column(String, index=True)
    type = Column(String)
    desc = Column(Text)
    systemPrompt = Column(Text)
    tools = Column(Text)

class SessionDB(Base):
    __tablename__ = "sessions"
    id = Column(String, primary_key=True, index=True)
    agentId = Column(String, index=True)
    title = Column(String)
    messages = Column(Text)
    isPinned = Column(Boolean, default=False)
    updatedAt = Column(BigInteger)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------------- Models ----------------
class Agent(BaseModel):
    id: str
    name: str
    type: str
    desc: str
    systemPrompt: str
    tools: list = []

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatSession(BaseModel):
    id: str
    agentId: str
    title: str
    messages: List[ChatMessage] = []
    isPinned: bool = False
    updatedAt: int

# ---------------- App Setup ----------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

client = AsyncOpenAI(api_key="sk-40fd6accfead48d8a3941fd8592efa17", base_url="https://api.deepseek.com")

# ---------------- REST Endpoints ----------------
@app.get("/api/agents", response_model=List[Agent])
def get_agents(db: Session = Depends(get_db)):
    agents = db.query(AgentDB).all()
    return [
        Agent(
            id=a.id, name=a.name, type=a.type, desc=a.desc,
            systemPrompt=a.systemPrompt, tools=json.loads(a.tools)
        ) for a in agents
    ]

@app.post("/api/agents")
def create_or_update_agent(agent: Agent, db: Session = Depends(get_db)):
    db_agent = db.query(AgentDB).filter(AgentDB.id == agent.id).first()
    if db_agent:
        db_agent.name = agent.name
        db_agent.type = agent.type
        db_agent.desc = agent.desc
        db_agent.systemPrompt = agent.systemPrompt
        db_agent.tools = json.dumps(agent.tools)
    else:
        new_agent = AgentDB(
            id=agent.id, name=agent.name, type=agent.type, desc=agent.desc,
            systemPrompt=agent.systemPrompt, tools=json.dumps(agent.tools)
        )
        db.add(new_agent)
    db.commit()
    return {"status": "success"}

@app.delete("/api/agents/{agent_id}")
def delete_agent(agent_id: str, db: Session = Depends(get_db)):
    db.query(AgentDB).filter(AgentDB.id == agent_id).delete()
    db.commit()
    return {"status": "success"}

@app.get("/api/sessions", response_model=List[ChatSession])
def get_sessions(db: Session = Depends(get_db)):
    sessions = db.query(SessionDB).order_by(SessionDB.updatedAt.desc()).all()
    return [
        ChatSession(
            id=s.id, agentId=s.agentId, title=s.title,
            messages=json.loads(s.messages), isPinned=s.isPinned, updatedAt=s.updatedAt
        ) for s in sessions
    ]

@app.post("/api/sessions")
def create_or_update_session(session: ChatSession, db: Session = Depends(get_db)):
    db_session = db.query(SessionDB).filter(SessionDB.id == session.id).first()
    if db_session:
        db_session.agentId = session.agentId
        db_session.title = session.title
        db_session.messages = json.dumps([m.model_dump() for m in session.messages])
        db_session.isPinned = session.isPinned
        db_session.updatedAt = session.updatedAt
    else:
        new_session = SessionDB(
            id=session.id, agentId=session.agentId, title=session.title,
            messages=json.dumps([m.model_dump() for m in session.messages]),
            isPinned=session.isPinned, updatedAt=session.updatedAt
        )
        db.add(new_session)
    db.commit()
    return {"status": "success"}

@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)):
    db.query(SessionDB).filter(SessionDB.id == session_id).delete()
    db.commit()
    return {"status": "success"}

@app.post("/api/create-agent")
async def create_agent(request: Request):
    data = await request.json()
    messages = data.get("messages", [])
    stream = data.get("stream", False)

    creator_prompt = """
You are AgentForge (智戎), an AI that helps users create their own custom AI assistants.
The user will describe the assistant they want to create.
If the user's description is vague or missing key details (like tone, specific tasks), ask 1-2 clarifying questions in Chinese.
If the description is clear and sufficient, reply to the user confirming the creation, and AT THE VERY END of your response, you MUST output the following exact XML block containing the configuration:
<AGENT_READY>
<NAME>Name of the agent</NAME>
<PROMPT>The complete, detailed system prompt for the new agent, instructing it how to behave</PROMPT>
</AGENT_READY>
"""
    msgs = [{"role": "system", "content": creator_prompt}] + messages
    response = await client.chat.completions.create(model="deepseek-chat", messages=msgs, stream=stream)

    if stream:
        async def generate():
            async for chunk in response:
                content = chunk.choices[0].delta.content or ""
                if content: yield f"data: {json.dumps({'content': content})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(generate(), media_type="text/event-stream")
    else:
        return {"message": response.choices[0].message.content}

@app.post("/api/chat")
async def chat(request: Request):
    data = await request.json()
    system_prompt = data.get("systemPrompt", "")
    messages = data.get("messages", [])
    stream = data.get("stream", False)

    msgs = []
    if system_prompt: msgs.append({"role": "system", "content": system_prompt})
    msgs.extend(messages)

    response = await client.chat.completions.create(model="deepseek-chat", messages=msgs, stream=stream)

    if stream:
        async def generate():
            async for chunk in response:
                content = chunk.choices[0].delta.content or ""
                if content: yield f"data: {json.dumps({'content': content})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(generate(), media_type="text/event-stream")
    else:
        return {"message": response.choices[0].message.content}

app.mount("/", StaticFiles(directory="public", html=True), name="public")
