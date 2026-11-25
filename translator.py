"""
云端翻译模块

支持：
- DeepL（推荐，质量高，有免费额度）
- OpenAI 兼容接口（OpenAI / 通义 / DeepSeek 等）

环境变量优先：
  DEEPL_API_KEY
  OPENAI_API_KEY / OPENAI_BASE_URL
"""

from __future__ import annotations

import os
import time
from typing import Optional

import requests

# 简单缓存：相同原文短时间内不重复请求
_cache: dict[str, tuple[float, str]] = {}
_CACHE_TTL = 30.0


def _from_cache(text: str) -> Optional[str]:
    item = _cache.get(text)
    if item and (time.time() - item[0]) < _CACHE_TTL:
        return item[1]
    return None


def _to_cache(text: str, translated: str) -> None:
    _cache[text] = (time.time(), translated)
    # 防止无限增长
    if len(_cache) > 200:
        oldest = sorted(_cache.items(), key=lambda x: x[1][0])[:50]
        for k, _ in oldest:
            _cache.pop(k, None)


class Translator:
    def __init__(
        self,
        provider: str = 'deepl',          # 'deepl' | 'openai'
        api_key: str = '',
        target_lang: str = 'EN',          # DeepL: EN, JA, KO...  OpenAI: English
        source_lang: str = 'ZH',
        openai_base_url: str = 'https://api.openai.com/v1',
        openai_model: str = 'gpt-4o-mini',
        timeout: float = 8.0,
    ):
        self.provider = provider.lower().strip()
        self.api_key = api_key or self._default_key()
        self.target_lang = target_lang
        self.source_lang = source_lang
        self.openai_base_url = openai_base_url.rstrip('/')
        self.openai_model = openai_model
        self.timeout = timeout
        self._deepl = None

        if not self.api_key:
            print(f'[翻译] 未配置 {self.provider} API Key，翻译将禁用')
        elif self.provider == 'deepl':
            try:
                import deepl
                self._deepl = deepl.DeepLClient(self.api_key)
                print('[翻译] DeepL 已就绪')
            except ImportError:
                print('[翻译] 未安装 deepl，将用 HTTP 调用。可执行: pip install deepl')
            except Exception as e:
                print(f'[翻译] DeepL 初始化失败: {e}')

    def _default_key(self) -> str:
        if self.provider == 'deepl':
            return os.environ.get('DEEPL_API_KEY', '')
        return os.environ.get('OPENAI_API_KEY', '')

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def translate(self, text: str) -> str:
        text = (text or '').strip()
        if not text or not self.enabled:
            return ''

        cached = _from_cache(text)
        if cached is not None:
            return cached

        try:
            if self.provider == 'deepl':
                result = self._translate_deepl(text)
            else:
                result = self._translate_openai(text)
            result = (result or '').strip()
            if result:
                _to_cache(text, result)
            return result
        except Exception as e:
            print(f'[翻译] 失败: {e}')
            return ''

    def _translate_deepl(self, text: str) -> str:
        if self._deepl is not None:
            # 官方 SDK
            target = self.target_lang
            # DeepL 英文建议 EN-US / EN-GB，简单映射
            if target.upper() in ('EN', 'ENGLISH'):
                target = 'EN-US'
            result = self._deepl.translate_text(
                text,
                source_lang=self.source_lang if self.source_lang else None,
                target_lang=target,
            )
            return result.text

        # HTTP 回退（支持 free / pro）
        key = self.api_key
        base = 'https://api-free.deepl.com' if key.endswith(':fx') else 'https://api.deepl.com'
        target = self.target_lang.upper()
        if target in ('EN', 'ENGLISH'):
            target = 'EN-US'
        resp = requests.post(
            f'{base}/v2/translate',
            headers={
                'Authorization': f'DeepL-Auth-Key {key}',
                'Content-Type': 'application/json',
            },
            json={
                'text': [text],
                'source_lang': self.source_lang.upper() if self.source_lang else None,
                'target_lang': target,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data['translations'][0]['text']

    def _translate_openai(self, text: str) -> str:
        # 语言名给模型看
        lang_map = {
            'EN': 'English', 'EN-US': 'English', 'EN-GB': 'English',
            'JA': 'Japanese', 'KO': 'Korean', 'FR': 'French',
            'DE': 'German', 'ES': 'Spanish', 'RU': 'Russian',
            'ZH': 'Chinese',
        }
        target_name = lang_map.get(self.target_lang.upper(), self.target_lang)
        system = (
            f'Translate the following Chinese live-stream subtitle into {target_name}. '
            'Output only the translation, no quotes or explanation.'
        )
        resp = requests.post(
            f'{self.openai_base_url}/chat/completions',
            headers={
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'model': self.openai_model,
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': text},
                ],
                'temperature': 0.2,
                'max_tokens': 256,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data['choices'][0]['message']['content'].strip()
