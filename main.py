import os
import json
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import FastAPI, Depends, Request, HTTPException, status
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, String, Text, Boolean, BigInteger, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from pydantic import BaseModel
from openai import AsyncOpenAI
import jwt
import httpx

# ---------------- Database Setup ----------------
SQLALCHEMY_DATABASE_URL = "mysql+pymysql://casdoor:casdoor_password@192.168.1.135:3306/casdoor"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class AgentDB(Base):
    __tablename__ = "agents"
    id = Column(String(255), primary_key=True, index=True)
    name = Column(String(255), index=True)
    type = Column(String(255))
    desc = Column(Text)
    systemPrompt = Column(Text)
    tools = Column(Text)
    userId = Column(String(255), index=True, nullable=True) # New field for user ownership

class SessionDB(Base):
    __tablename__ = "sessions"
    id = Column(String(255), primary_key=True, index=True)
    agentId = Column(String(255), index=True)
    title = Column(String(255))
    messages = Column(Text)
    isPinned = Column(Boolean, default=False)
    updatedAt = Column(BigInteger)
    userId = Column(String(255), index=True, nullable=True) # New field for user ownership

Base.metadata.create_all(bind=engine)

# Auto-migration: check and add userId column if missing in existing SQLite database
with engine.connect() as conn:
    inspector = inspect(engine)
    
    # Migrate agents table
    agents_cols = [c['name'] for c in inspector.get_columns('agents')]
    if 'userId' not in agents_cols:
        try:
            conn.execute(text("ALTER TABLE agents ADD COLUMN userId TEXT"))
            conn.commit()
            print("Successfully migrated database table 'agents': added 'userId' column.")
        except Exception as e:
            print("Migration warning (agents):", e)
            
    # Migrate sessions table
    sessions_cols = [c['name'] for c in inspector.get_columns('sessions')]
    if 'userId' not in sessions_cols:
        try:
            conn.execute(text("ALTER TABLE sessions ADD COLUMN userId TEXT"))
            conn.commit()
            print("Successfully migrated database table 'sessions': added 'userId' column.")
        except Exception as e:
            print("Migration warning (sessions):", e)

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
    userId: Optional[str] = None

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
    userId: Optional[str] = None

# ---------------- Auth Configuration & Helpers ----------------
CASDOOR_ENDPOINT = "http://192.168.1.135:8000"
CASDOOR_CLIENT_ID = "be52450276ed83ab1c0e"
CASDOOR_CLIENT_SECRET = "22dfe48babe0fc03f7321e36047fe10f2b9b64da"
CASDOOR_ORGANIZATION = "built-in"
CASDOOR_APPLICATION = "app-built-in"

JWT_SECRET_KEY = "agentforge-super-secret-key-change-in-prod"
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440 # Token valid for 24 hours

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt

# Dependency Injection to verify local JWT token and return authenticated user details
async def get_current_user(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("id")
        username = payload.get("username")
        if user_id is None or username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )
        class CurrentUser:
            def __init__(self, id, username):
                self.id = id
                self.username = username
        return CurrentUser(id=user_id, username=username)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token verification failed or token expired",
        )

# ---------------- App Setup ----------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

client = AsyncOpenAI(api_key="sk-40fd6accfead48d8a3941fd8592efa17", base_url="https://api.deepseek.com")

# ---------------- Auth Endpoints ----------------
@app.get("/api/auth/config")
def get_auth_config():
    return {
        "casdoorEndpoint": CASDOOR_ENDPOINT,
        "clientId": CASDOOR_CLIENT_ID,
        "organization": CASDOOR_ORGANIZATION,
        "application": CASDOOR_APPLICATION
    }

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/auth/login")
async def auth_login(req: LoginRequest):
    username = req.username.strip()
    password = req.password
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    
    # Authenticate with Casdoor using Resource Owner Password Credentials (ROPC)
    token_url = f"{CASDOOR_ENDPOINT}/api/login/oauth/access_token"
    data = {
        "grant_type": "password",
        "username": username,
        "password": password,
        "client_id": CASDOOR_CLIENT_ID,
        "client_secret": CASDOOR_CLIENT_SECRET,
    }
    
    try:
        async with httpx.AsyncClient(trust_env=False) as client_http:
            res = await client_http.post(token_url, data=data)
            if res.status_code != 200:
                res_data = res.json()
                err_desc = res_data.get("error_description") or res_data.get("error") or "登录失败"
                raise HTTPException(status_code=400, detail=err_desc)
            
            res_data = res.json()
            id_token = res_data.get("id_token")
            if not id_token:
                raise HTTPException(status_code=400, detail="认证服务未返回有效 ID Token")
            
            # Decode payload without verifying signature since it comes directly from local VM
            payload = jwt.decode(id_token, options={"verify_signature": False})
            user_id = payload.get("id") or payload.get("sub")
            username = payload.get("name") or payload.get("preferred_username") or username
            
            if not user_id:
                raise HTTPException(status_code=400, detail="无效的 Token 荷载")
            
            # Issue local JWT token
            token = create_access_token({"id": user_id, "username": username})
            return {"token": token, "username": username}
            
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"认证异常: {str(e)}")

class RegisterRequest(BaseModel):
    username: str
    password: str

@app.post("/api/auth/register")
async def auth_register(req: RegisterRequest):
    username = req.username.strip()
    password = req.password
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码长度不能少于 6 位")
    
    # Call Casdoor signup API
    signup_url = f"{CASDOOR_ENDPOINT}/api/signup"
    json_data = {
        "username": username,
        "password": password,
        "confirmPassword": password,
        "application": CASDOOR_APPLICATION,
        "organization": CASDOOR_ORGANIZATION
    }
    
    try:
        async with httpx.AsyncClient(trust_env=False) as client_http:
            res = await client_http.post(signup_url, json=json_data)
            if res.status_code != 200:
                raise HTTPException(status_code=400, detail="注册服务通信失败")
            
            res_data = res.json()
            if res_data.get("status") == "error":
                raise HTTPException(status_code=400, detail=res_data.get("msg") or "注册失败")
            
            return {"status": "success", "message": "注册成功"}
            
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"注册异常: {str(e)}")


class CallbackRequest(BaseModel):
    code: str
    state: str = None

@app.post("/api/auth/callback")
async def auth_callback(req: CallbackRequest):
    # 1. Exchange authorization code for access token with Casdoor
    token_url = f"{CASDOOR_ENDPOINT}/api/login/oauth/access_token"
    data = {
        "grant_type": "authorization_code",
        "client_id": CASDOOR_CLIENT_ID,
        "client_secret": CASDOOR_CLIENT_SECRET,
        "code": req.code,
    }
    try:
        async with httpx.AsyncClient() as client_http:
            res = await client_http.post(token_url, data=data)
            if res.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to request token from Casdoor")
            res_data = res.json()
            access_token = res_data.get("access_token")
            if not access_token:
                raise HTTPException(status_code=400, detail=f"No access token returned: {res.text}")
            
            # 2. Request userinfo using access token
            userinfo_url = f"{CASDOOR_ENDPOINT}/api/userinfo?access_token={access_token}"
            user_res = await client_http.get(userinfo_url)
            if user_res.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to fetch userinfo from Casdoor")
            
            user_data = user_res.json()
            user_id = user_data.get("sub") or user_data.get("id") or user_data.get("name")
            username = user_data.get("name") or user_data.get("preferred_username")
            
            if not user_id or not username:
                raise HTTPException(status_code=400, detail="Invalid user metadata received from Casdoor")
            
            # 3. Issue local JWT token
            token = create_access_token({"id": user_id, "username": username})
            return {"token": token, "username": username}
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OIDC callback error: {str(e)}")

# ---------------- REST Endpoints ----------------
@app.get("/api/agents", response_model=List[Agent])
def get_agents(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    # Query only current user's agents or historical public agents (where userId is null)
    agents = db.query(AgentDB).filter((AgentDB.userId == current_user.id) | (AgentDB.userId == None)).all()
    return [
        Agent(
            id=a.id, name=a.name, type=a.type, desc=a.desc,
            systemPrompt=a.systemPrompt, tools=json.loads(a.tools), userId=a.userId
        ) for a in agents
    ]

@app.post("/api/agents")
def create_or_update_agent(agent: Agent, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    db_agent = db.query(AgentDB).filter(AgentDB.id == agent.id).first()
    if db_agent:
        # Prevent unauthorized updates (horizontal privilege escalation check)
        if db_agent.userId and db_agent.userId != current_user.id:
            raise HTTPException(status_code=403, detail="Permission denied")
        db_agent.name = agent.name
        db_agent.type = agent.type
        db_agent.desc = agent.desc
        db_agent.systemPrompt = agent.systemPrompt
        db_agent.tools = json.dumps(agent.tools)
        db_agent.userId = current_user.id
    else:
        new_agent = AgentDB(
            id=agent.id, name=agent.name, type=agent.type, desc=agent.desc,
            systemPrompt=agent.systemPrompt, tools=json.dumps(agent.tools),
            userId=current_user.id
        )
        db.add(new_agent)
    db.commit()
    return {"status": "success"}

@app.delete("/api/agents/{agent_id}")
def delete_agent(agent_id: str, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    db_agent = db.query(AgentDB).filter(AgentDB.id == agent_id).first()
    if not db_agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if db_agent.userId and db_agent.userId != current_user.id:
        raise HTTPException(status_code=403, detail="Permission denied")
    db.delete(db_agent)
    db.commit()
    return {"status": "success"}

@app.get("/api/sessions", response_model=List[ChatSession])
def get_sessions(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    # Query only sessions owned by the current user
    sessions = db.query(SessionDB).filter((SessionDB.userId == current_user.id) | (SessionDB.userId == None)).order_by(SessionDB.updatedAt.desc()).all()
    return [
        ChatSession(
            id=s.id, agentId=s.agentId, title=s.title,
            messages=json.loads(s.messages), isPinned=s.isPinned, updatedAt=s.updatedAt, userId=s.userId
        ) for s in sessions
    ]

@app.post("/api/sessions")
def create_or_update_session(session: ChatSession, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    db_session = db.query(SessionDB).filter(SessionDB.id == session.id).first()
    if db_session:
        if db_session.userId and db_session.userId != current_user.id:
            raise HTTPException(status_code=403, detail="Permission denied")
        db_session.agentId = session.agentId
        db_session.title = session.title
        db_session.messages = json.dumps([m.model_dump() for m in session.messages])
        db_session.isPinned = session.isPinned
        db_session.updatedAt = session.updatedAt
        db_session.userId = current_user.id
    else:
        new_session = SessionDB(
            id=session.id, agentId=session.agentId, title=session.title,
            messages=json.dumps([m.model_dump() for m in session.messages]),
            isPinned=session.isPinned, updatedAt=session.updatedAt,
            userId=current_user.id
        )
        db.add(new_session)
    db.commit()
    return {"status": "success"}

@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    db_session = db.query(SessionDB).filter(SessionDB.id == session_id).first()
    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found")
    if db_session.userId and db_session.userId != current_user.id:
        raise HTTPException(status_code=403, detail="Permission denied")
    db.delete(db_session)
    db.commit()
    return {"status": "success"}

@app.post("/api/create-agent")
async def create_agent(request: Request, current_user = Depends(get_current_user)):
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
async def chat(request: Request, current_user = Depends(get_current_user)):
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
