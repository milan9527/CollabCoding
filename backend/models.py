"""Pydantic models for API request/response schemas."""
from pydantic import BaseModel
from typing import Optional
from enum import Enum


class UserRole(str, Enum):
    DEVELOPER = "developer"
    DESIGNER = "designer"
    PRODUCT_MANAGER = "product_manager"


class User(BaseModel):
    user_id: str
    username: str
    role: UserRole
    avatar_color: Optional[str] = "#6366f1"


class Space(BaseModel):
    space_id: str
    name: str
    description: Optional[str] = ""
    owner_id: str
    session_id: str


class FileNode(BaseModel):
    path: str
    name: str
    content: Optional[str] = ""
    language: Optional[str] = "html"
    is_directory: bool = False


class AgentRequest(BaseModel):
    space_id: str
    prompt: str
    user_id: str
    session_id: Optional[str] = None


class AgentResponse(BaseModel):
    response: str
    files_changed: list[str] = []
    session_id: str


class FileUpdate(BaseModel):
    space_id: str
    file_path: str
    content: str
    user_id: str


class ChatMessage(BaseModel):
    message_id: str
    space_id: str
    user_id: str
    username: str
    role: UserRole
    content: str
    timestamp: str
    is_agent: bool = False
