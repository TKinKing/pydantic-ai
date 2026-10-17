"""所有学习专题共用模型配置：有 DeepSeek Key 用云端，否则用本地 Ollama."""

from os import getenv

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider
from pydantic_ai.providers.ollama import OllamaProvider

# 有值时使用 DeepSeek；留空时使用本地 Ollama。F5 也会读取根目录 .env。
DEEPSEEK_API_KEY = getenv('DEEPSEEK_API_KEY', '')
DEEPSEEK_MODEL = 'deepseek-v4-flash'
OLLAMA_MODEL = getenv('OLLAMA_MODEL', 'qwen2.5-harness:14b-16k')
OLLAMA_BASE_URL = getenv('OLLAMA_BASE_URL', 'http://localhost:11434/v1')


def create_model() -> OpenAIChatModel:
    """只根据 Key 是否为空选择服务，失败时不会悄悄切换模型."""
    if api_key := DEEPSEEK_API_KEY.strip():
        return OpenAIChatModel(
            DEEPSEEK_MODEL,
            provider=DeepSeekProvider(api_key=api_key),
            settings={'thinking': False},
        )
    return OpenAIChatModel(OLLAMA_MODEL, provider=OllamaProvider(base_url=OLLAMA_BASE_URL))
