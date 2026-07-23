"""
설정 로더.

.env 파일에서 API 키와 옵션을 읽어들여 하나의 Settings 객체로 제공합니다.
비개발자 설명: 프로그램 전체가 쓰는 '환경설정 카드' 한 장이라고 보시면 됩니다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# 프로젝트 루트 (이 파일 기준 상위 폴더)
ROOT = Path(__file__).resolve().parent.parent

# .env 파일을 읽어 환경변수로 로드
load_dotenv(ROOT / ".env")


@dataclass
class Settings:
    # --- AI 엔진 선택: auto | claude | gemini | rule ---
    #   auto = 키가 있는 엔진 자동 선택(claude 우선 → gemini → 없으면 규칙 기반)
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "auto").lower())

    # --- API 키 ---
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8"))
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-flash-latest"))
    dart_api_key: str = field(default_factory=lambda: os.getenv("DART_API_KEY", ""))

    # --- 경로 ---
    root: Path = ROOT
    output_dir: Path = ROOT / "output"
    cache_dir: Path = ROOT / "cache"

    def __post_init__(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # --- 상태 점검 ---
    @property
    def has_dart(self) -> bool:
        return bool(self.dart_api_key)

    def active_provider(self) -> str:
        """실제로 사용할 AI 엔진을 결정. 키가 없으면 'rule'(규칙 기반)."""
        p = self.llm_provider
        if p == "claude":
            return "claude" if self.anthropic_api_key else "rule"
        if p == "gemini":
            return "gemini" if self.gemini_api_key else "rule"
        if p == "claude_code":
            # 로컬 Claude Code CLI(구독) 사용. 별도 API 키 불필요.
            return "claude_code"
        if p == "rule":
            return "rule"
        # auto: 있는 키를 우선순위대로 선택 (claude_code는 명시 지정 시에만)
        if self.anthropic_api_key:
            return "claude"
        if self.gemini_api_key:
            return "gemini"
        return "rule"

    def active_model(self) -> str:
        prov = self.active_provider()
        return {
            "claude": self.anthropic_model,
            "gemini": self.gemini_model,
            "claude_code": "Claude Code CLI (구독)",
        }.get(prov, "-")

    def summary(self) -> str:
        def mark(ok: bool) -> str:
            return "✅ 설정됨" if ok else "❌ 없음"
        prov = self.active_provider()
        label = {"claude": "Claude", "gemini": "Gemini",
                 "claude_code": "Claude Code(구독)", "rule": "규칙 기반(AI 미적용)"}[prov]
        return (
            f"  - AI 엔진(현재 사용)   : {label}"
            + (f"  (모델: {self.active_model()})" if prov != "rule" else "") + "\n"
            f"    · Anthropic(Claude) 키: {mark(bool(self.anthropic_api_key))}\n"
            f"    · Google(Gemini) 키   : {mark(bool(self.gemini_api_key))}\n"
            f"  - DART Open API 키     : {mark(self.has_dart)}"
        )


# 전역에서 재사용하는 단일 설정 인스턴스
settings = Settings()
