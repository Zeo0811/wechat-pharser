from __future__ import annotations
import json
import os
from pydantic import BaseModel


class Config(BaseModel):
    notion_token: str = ""
    notion_parent_page_id: str = ""
    notion_companies_db_id: str = ""
    notion_people_db_id: str = ""
    notion_links_db_id: str = ""
    max_messages_per_chunk: int = 100
    prompt_version: str = "v1"
    cache_dir: str = ".qun_cache"


def load_config(path: str = "config.json") -> Config:
    if not os.path.exists(path):
        raise FileNotFoundError(f"配置文件不存在：{path}（可复制 config.example.json）")
    with open(path, "r", encoding="utf-8") as f:
        return Config(**json.load(f))
