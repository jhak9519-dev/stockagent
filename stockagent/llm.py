"""
AI 엔진 래퍼 (Claude API / Gemini / Claude Code CLI 공용 창구).

분석 에이전트는 이 파일의 `llm` 객체만 사용합니다. 실제 엔진은 `.env`의
LLM_PROVIDER 및 보유 키에 따라 자동 선택됩니다(config.active_provider()).
- claude      : Anthropic Claude API (유료 종량제 키 필요)
- gemini      : Google Gemini API (무료 티어 사용 가능)
- claude_code : 로컬 Claude Code CLI(`claude -p`)를 구독 계정으로 호출 (API 키 불필요)
- rule        : 엔진 없음 → 호출 측에서 규칙 기반 요약으로 대체
엔진이 없으면 available=False가 되어 각 에이전트가 규칙 기반 서술로 넘어갑니다.
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any, Optional

from .config import settings


def _log_llm_error(msg: str) -> None:
    """AI 엔진 호출 실패 원인을 logs/llm_errors.log 에 영구 기록.

    배치의 stdout 리다이렉트가 실패해도(무인 환경 이슈) 원인이 남도록 파일에 직접 쓴다.
    """
    try:
        from datetime import datetime

        from .config import ROOT
        p = ROOT / "logs" / "llm_errors.log"
        p.parent.mkdir(exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:
        pass


class LLM:
    def __init__(self) -> None:
        self.provider = settings.active_provider()
        self.model = settings.active_model()
        self._client = None
        self._warned = False  # AI 호출 실패 경고를 1회만 출력
        self.fallback_used = False  # 규칙 기반 폴백이 한 번이라도 발생했는지 (알림용)

        if self.provider == "claude":
            from anthropic import Anthropic
            self._client = Anthropic(api_key=settings.anthropic_api_key)
        elif self.provider == "gemini":
            # google-genai 패키지는 실제 사용 시에만 import
            from google import genai
            self._client = genai.Client(api_key=settings.gemini_api_key)
        elif self.provider == "claude_code":
            # 로컬 `claude -p` CLI를 구독 계정으로 호출. 클라이언트 객체 불필요(센티넬).
            self._client = "cli"

    @property
    def available(self) -> bool:
        return self._client is not None

    # -- 내부: 1회 호출(예외 발생 가능) ---------------------------------------
    def _call_once(self, prompt: str, system: str, max_tokens: int,
                   temperature: float, json_mode: bool) -> str:
        if self.provider == "claude":
            msg = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in msg.content if b.type == "text").strip()

        if self.provider == "gemini":
            from google.genai import types
            # thinking을 끄지 않으면 flash(3.x)가 출력 토큰을 '사고'에 소모해
            # 실제 답변이 비거나 잘림 → thinking_budget=0으로 전량 답변에 사용.
            cfg = types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
                max_output_tokens=max_tokens,
                response_mime_type="application/json" if json_mode else None,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            )
            resp = self._client.models.generate_content(
                model=self.model, contents=prompt, config=cfg,
            )
            return (resp.text or "").strip()

        if self.provider == "claude_code":
            # `claude -p`는 대화형 어시스턴트라 부연·제안·면책 문구가 붙기 쉬움 → 결과물만 강제.
            guard = (
                "[출력 규칙] 아래 요청의 '결과물'만 출력하세요. 인사말, 부연 설명, 메타 코멘트, "
                "제안('~해드릴까요' 등), 면책·실시간 데이터 관련 언급, 구분선(---)을 포함하지 마세요. "
                "JSON을 요청하면 JSON 객체만, 서술을 요청하면 본문 서술만 출력하세요."
            )
            # 시스템+규칙+프롬프트를 합쳐 stdin으로 전달(따옴표/줄바꿈 안전). Claude Code 구독으로 처리.
            full = f"{system}\n\n{guard}\n\n{prompt}"
            try:
                r = subprocess.run(
                    "claude -p --output-format json",
                    input=full, capture_output=True, text=True,
                    encoding="utf-8", shell=True, timeout=180,
                )
            except subprocess.TimeoutExpired:
                # 무인(S4U) 세션에서 로그인/응답 지연으로 멈추는 대표 증상 — 원인 추적용 기록
                _log_llm_error("claude -p 180초 타임아웃 — 무인 세션 로그인/응답 지연 의심(claude 재로그인 확인)")
                raise
            if r.returncode != 0 or not (r.stdout or "").strip():
                _log_llm_error(f"claude -p 비정상 종료 rc={r.returncode} stderr={(r.stderr or '')[:300]}")
                return ""
            try:
                data = json.loads(r.stdout)
            except json.JSONDecodeError:
                _log_llm_error(f"claude -p JSON 파싱 실패: {(r.stdout or '')[:200]}")
                return ""
            if data.get("is_error") or data.get("subtype") != "success":
                _log_llm_error(f"claude -p 오류 subtype={data.get('subtype')} "
                               f"status={data.get('api_error_status')} result={str(data.get('result',''))[:200]}")
                return ""  # 미로그인/오류 → 규칙 기반 폴백
            return (data.get("result") or "").strip()
        return ""

    # -- 내부: 재시도 포함 호출 -----------------------------------------------
    def _generate(self, prompt: str, system: str, max_tokens: int,
                  temperature: float, json_mode: bool) -> str:
        # 무료티어의 일시적 503/빈응답에 대비해 최대 2회 시도. 모두 실패 시 규칙 기반 폴백.
        last_err = ""
        for attempt in range(2):
            try:
                text = self._call_once(prompt, system, max_tokens, temperature, json_mode)
                if text:
                    return text
            except Exception as e:
                last_err = str(e)[:160]
        self.fallback_used = True  # 리포트/카톡에 '폴백 발생' 표시용
        if not self._warned:
            reason = last_err or "빈 응답"
            print(f"    ⚠ AI 엔진({self.provider}) 호출 실패 → 규칙 기반으로 대체합니다: {reason}")
            self._warned = True
        return ""

    # -- 공개 API --------------------------------------------------------------
    def ask(
        self,
        prompt: str,
        system: str = "당신은 국내외 주식을 분석하는 증권사 리서치센터의 애널리스트입니다.",
        max_tokens: int = 2000,
        temperature: float = 0.4,
    ) -> str:
        """자유 서술 텍스트 응답."""
        if not self.available:
            self.fallback_used = True
            return "[AI 엔진 미설정으로 서술이 생성되지 않았습니다.]"
        return self._generate(prompt, system, max_tokens, temperature, json_mode=False)

    def ask_json(
        self,
        prompt: str,
        system: str = "당신은 증권사 리서치센터의 애널리스트입니다. 반드시 유효한 JSON만 출력하세요.",
        max_tokens: int = 2000,
        temperature: float = 0.3,
    ) -> Optional[dict[str, Any]]:
        """구조화된 JSON 응답을 dict로 파싱. 실패 시 None."""
        if not self.available:
            return None
        raw = self._generate(
            prompt + "\n\n반드시 JSON 객체 하나만 출력하세요. 코드블록/설명 금지.",
            system, max_tokens, temperature, json_mode=True,
        )
        return _extract_json(raw)


def _extract_json(text: str) -> Optional[dict[str, Any]]:
    """응답에서 첫 번째 JSON 객체를 추출."""
    text = re.sub(r"```(?:json)?", "", text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


# 전역 단일 인스턴스
llm = LLM()
