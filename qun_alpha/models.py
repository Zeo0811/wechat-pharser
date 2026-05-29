from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field

Status = Literal["emerging", "known", "noise", "unclear"]


class Message(BaseModel):
    msg_id: str
    group_id: str
    group_name: str
    sender: str
    timestamp: int            # epoch seconds
    text: str
    msg_type: str = "text"


class MessageChunk(BaseModel):
    chunk_id: str             # hash(group_id + time_start + time_end + prompt_version)
    group_id: str
    group_name: str
    time_start: int
    time_end: int
    messages: list[Message]


class SourceRef(BaseModel):
    group_name: str
    sender: str
    timestamp: int
    msg_id: str


class RawEntity(BaseModel):
    """extractor 从单块吐出的原始观察，未聚合。"""
    kind: Literal["company", "person", "link"]
    name: str
    quote: str = ""           # 原文引用
    commentary: str = ""      # 模型点评
    source: SourceRef
    # company 相关（可选）
    sector: Optional[str] = None
    stage: Optional[str] = None
    financials: Optional[str] = None
    investors: list[str] = Field(default_factory=list)
    sentiment: Optional[str] = None
    catalyst: Optional[str] = None
    risk: Optional[str] = None
    suggested_action: Optional[str] = None
    confidence: Optional[float] = None
    related_people: list[str] = Field(default_factory=list)
    # person 相关
    role: Optional[str] = None
    affiliated_company: Optional[str] = None
    # link 相关
    url: Optional[str] = None
    title: Optional[str] = None
    related_company: Optional[str] = None


class Company(BaseModel):
    name: str
    score: int                # 0-100
    mentions: int
    status: Status
    signal: str               # 合成：引用 + 点评
    first_seen: int
    last_seen: int
    sector: Optional[str] = None
    stage: Optional[str] = None
    financials: Optional[str] = None
    investors: list[str] = Field(default_factory=list)
    sentiment: Optional[str] = None
    catalyst: Optional[str] = None
    risk: Optional[str] = None
    suggested_action: Optional[str] = None
    confidence: float = 0.0
    related_people: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)


class Person(BaseModel):
    name: str
    mentions: int
    role: Optional[str] = None
    affiliated_companies: list[str] = Field(default_factory=list)
    notable_quotes: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)


class Link(BaseModel):
    url: str
    title: Optional[str] = None
    shared_by: list[str] = Field(default_factory=list)
    related_companies: list[str] = Field(default_factory=list)
    first_seen: int = 0
    sources: list[SourceRef] = Field(default_factory=list)
