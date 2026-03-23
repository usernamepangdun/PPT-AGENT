import os
from dotenv import load_dotenv

load_dotenv(override=True)

# 支持的 AI Provider 配置
PROVIDERS = {
    "openai": {
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
        "reasoning_effort": os.getenv("OPENAI_REASONING_EFFORT", "high"),
    },
    "claude": {
        "api_key": os.getenv("CLAUDE_API_KEY", ""),
        "base_url": "https://api.anthropic.com/v1",
        "model": os.getenv("CLAUDE_MODEL", "claude-opus-4-6"),
    },
    "domestic": {
        "api_key": os.getenv("DOMESTIC_API_KEY", ""),
        "base_url": os.getenv("DOMESTIC_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "model": os.getenv("DOMESTIC_MODEL", "qwen-plus"),
    },
}

# 默认使用的 provider
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "openai")

# 输出目录
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "./output")
