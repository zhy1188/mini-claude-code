"""Configuration management via nexus.toml."""

import os
from pathlib import Path

import tomllib
from pydantic import BaseModel, Field


class BashConfig(BaseModel):
    timeout: int = 120
    max_output_bytes: int = 50_000
    dangerous_patterns: list[str] = Field(
        default_factory=lambda: ["rm -rf /", "sudo", ":(){:|:&};:"]
    )


class ContextConfig(BaseModel):
    max_tokens: int = 200_000
    compact_threshold: float = 0.75
    compact_strategy: str = "llm_summary"


class LLMConfig(BaseModel):
    provider: str = "anthropic"
    model: str = "qwen3.6-plus"
    api_key: str = ""
    max_tokens: int = 8192
    temperature: float = 0.7
    base_url: str = ""
    thinking_budget: int = 0  # Extended thinking: 0=disabled, >0=enabled


class PermissionConfig(BaseModel):
    Read: str = "approve"
    Glob: str = "approve"
    Grep: str = "approve"
    Write: str = "ask"
    Bash: str = "ask"
    Task: str = "ask"


class MemoryConfig(BaseModel):
    enabled: bool = True
    auto_save_sessions: bool = True
    max_memories_per_type: int = 50


class AgentConfig(BaseModel):
    max_iterations: int = 50
    max_duration_minutes: float = 0  # 0 = unlimited
    sub_agent_timeout_seconds: int = 300  # 0 = unlimited


class NexusConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    permissions: PermissionConfig = Field(default_factory=PermissionConfig)
    bash: BashConfig = Field(default_factory=BashConfig)
    mcp: dict[str, str] = Field(default_factory=dict)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)


def _resolve_env_vars(value: str) -> str:
    """解析配置值中的 ${ENV_VAR} 模式"""
    if value.startswith("${") and value.endswith("}"):
        var_name = value[2:-1]
        return os.environ.get(var_name, "")
    return value


def load_config(path: Path | None = None) -> NexusConfig:
    """从 nexus.toml 加载配置，回退到默认值"""
    if path is None:
        path = Path("nexus.toml")
    if not path.exists():
        return NexusConfig()

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    # 解析 LLM api_key 中的环境变量
    if "llm" in raw and "api_key" in raw["llm"]:
        raw["llm"]["api_key"] = _resolve_env_vars(raw["llm"]["api_key"])

    return NexusConfig(**raw)
