"""
카카오톡 '나에게 보내기' 알림 (카카오 REST API).

무인 스케줄러 배치가 끝났을 때 리포트 요약을 카톡으로 보내기 위한 모듈입니다.

사전 준비(1회만):
  1) developers.kakao.com 에서 앱 등록 → REST API 키 발급
  2) python tools/kakao_auth.py 실행 → 브라우저에서 카카오 로그인·동의
     → 토큰이 .env 에 자동 저장됩니다.
이후에는 배치가 끝날 때마다 자동으로 요약 메시지가 전송됩니다.

비개발자 설명(토큰 구조):
  - access token  : 수명이 짧은 '출입증'(약 6시간). 보낼 때마다 새로 발급받아 씁니다.
  - refresh token : 출입증을 재발급받는 '장기 회원권'(약 2개월). 갱신 응답에
    새 회원권이 오면 .env 에 자동으로 갱신 저장되므로 계속 쓰는 한 만료되지 않습니다.
"""
from __future__ import annotations

import json
import os

import requests

from .config import ROOT

_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
_MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


def enabled() -> bool:
    """카카오 알림 설정이 완료되어 있는지 (REST 키 + refresh token 둘 다 필요).

    STOCKAGENT_NO_PUBLISH 가 설정되면(테스트·진단 실행) 알림을 보내지 않는다
    — 웹 발행(publish)·이메일(mailer)과 동일한 안전 스위치.
    """
    if os.getenv("STOCKAGENT_NO_PUBLISH"):
        return False
    return bool(os.getenv("KAKAO_REST_API_KEY")) and bool(os.getenv("KAKAO_REFRESH_TOKEN"))


def _update_env(key: str, value: str) -> None:
    """.env 파일의 key=value 를 갱신(없으면 추가)하고, 현재 프로세스 환경에도 반영."""
    env_path = ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value


def _fresh_access_token() -> str:
    """refresh token으로 새 access token 발급. 새 refresh token이 오면 .env에 저장."""
    data = {
        "grant_type": "refresh_token",
        "client_id": os.getenv("KAKAO_REST_API_KEY", ""),
        "refresh_token": os.getenv("KAKAO_REFRESH_TOKEN", ""),
    }
    # 앱에 Client Secret이 활성화된 경우 필수 (없으면 KOE010 오류)
    secret = os.getenv("KAKAO_CLIENT_SECRET", "")
    if secret:
        data["client_secret"] = secret
    resp = requests.post(_TOKEN_URL, data=data, timeout=15)
    resp.raise_for_status()
    tok = resp.json()
    if tok.get("refresh_token"):  # 만료 임박 시에만 새로 내려옴 → 자동 교체
        _update_env("KAKAO_REFRESH_TOKEN", tok["refresh_token"])
    return tok["access_token"]


def send_text(text: str, link_url: str = "", button_title: str = "자세히 보기") -> bool:
    """'나와의 채팅'으로 텍스트 전송(최대 200자). 성공 여부 반환(실패해도 예외를 내지 않음).

    link_url 지정 시 메시지 하단에 button_title 문구의 버튼이 생깁니다.
    ⚠ 버튼이 실제로 보이려면 해당 도메인이 카카오 콘솔의
      [앱 > 제품 링크 관리 > 웹 도메인] 에 등록되어 있어야 합니다(미등록 시 버튼만 조용히 사라짐).
    ⚠ 링크를 비워 보내면 카카오가 기본 [자세히 보기] 버튼을 빈 주소로 만들어 404가 나므로,
      링크가 없으면 리포트 목록 페이지로 연결한다 (2026-07-16 사용자 리포트로 발견된 버그).
    """
    if not link_url:
        try:
            from .report.publish import BASE_URL
            link_url = BASE_URL + "/"
        except Exception:
            pass
    try:
        access = _fresh_access_token()
        template = {
            "object_type": "text",
            "text": text[:200],
            "link": {"web_url": link_url, "mobile_web_url": link_url} if link_url else {},
        }
        if link_url:
            template["button_title"] = button_title
        resp = requests.post(
            _MEMO_URL,
            headers={"Authorization": f"Bearer {access}"},
            data={"template_object": json.dumps(template, ensure_ascii=False)},
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception as e:  # 알림 실패가 배치 전체를 망치지 않도록 흡수
        print(f"    ⚠ 카톡 알림 전송 실패(리포트는 정상 저장됨): {e}")
        return False


def _split_sentences(text: str, limit: int = 185, max_chunks: int = 2) -> list[str]:
    """긴 글을 문장 경계('다.') 기준으로 limit자 이하 덩어리로 분할. 최대 max_chunks개.

    카카오 텍스트 메시지가 200자 제한이므로, 투자 요약을 2건 정도로 나눠 보내기 위한 도우미.
    잘린 경우 마지막 덩어리 끝에 '…(이하 PDF)'를 붙여 전문이 더 있음을 알립니다.
    """
    text = text.replace("**", "")  # 리포트용 강조 마커는 카톡에선 제거
    text = " ".join(text.split())  # 공백·줄바꿈 정리
    chunks: list[str] = []
    rest = text
    while rest and len(chunks) < max_chunks:
        if len(rest) <= limit:
            chunks.append(rest)
            rest = ""
            break
        cut = rest.rfind("다.", 0, limit)  # 문장 끝에서 자르기
        cut = cut + 2 if cut > 40 else limit  # 문장 경계가 너무 앞이면 그냥 limit에서
        chunks.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest and chunks:  # 다 못 담은 경우 표시
        chunks[-1] = chunks[-1][:limit - 10].rstrip() + " …(이하 PDF)"
    return chunks


def send_report_summary(report, fallback: bool = False) -> bool:
    """리포트를 카톡 '1건'으로 압축 전송 (2026-07-16 사용자 확정: 2건은 지저분).

    핵심 수치만 담고, 상세 분석은 [리포트 보기] 버튼(웹 리포트)으로 유도한다.
    fallback=True 면 'AI 폴백 발생' 경고 한 줄을 추가한다(품질 저하 즉시 인지용).
    """
    d, v = report.data, report.valuation
    cur = "₩" if d.market == "KR" else "$"

    def fmt(x) -> str:
        if x is None:
            return "-"
        return f"{x:,.0f}" if d.market == "KR" else f"{x:,.2f}"

    # 항목별 줄바꿈 + 빈 줄 구분으로 한눈에 읽히게 (2026-07-16 사용자 요청)
    lines = [
        "[StockAgent] 오늘의 종목",
        f"{d.name} ({d.ticker}) · {v.opinion}",
        "",
        f"목표가 {cur}{fmt(v.target_price)}"
        + (f" ({v.upside_pct:+.1f}%)" if v.upside_pct is not None else ""),
    ]
    if getattr(v, "buy_low", None) and getattr(v, "buy_high", None):
        lines.append(f"매수 {cur}{fmt(v.buy_low)} ~ {fmt(v.buy_high)}")
        lines.append(f"손절 {cur}{fmt(v.stop_loss)}")
    elif v.buy_price:
        lines.append(f"매수 {cur}{fmt(v.buy_price)}")
        lines.append(f"손절 {cur}{fmt(v.stop_loss)}")
    warns = []
    try:  # 단기 과열 신호(급등 후 고점 인접) 경고
        from .agents.context import overheat_flag
        if overheat_flag(d):
            warns.append("⚠ 단기 과열 — 추격매수 주의")
    except Exception:
        pass
    if fallback:
        warns.append("⚠ 일부 섹션 규칙기반 대체(AI 폴백)")
    if warns:
        lines.append("")
        lines.extend(warns)
    lines.extend(["", "상세 분석 → 아래 [리포트 보기]"])

    # 버튼 링크: 웹 발행된 리포트 페이지 우선, 없으면 종목 시세 페이지
    web = getattr(report, "web_url", None)
    if web:
        # 캐시 무효화: GitHub Pages(max-age=600)·카톡 내장 브라우저가 이전 버전을
        # 보여주지 않도록 발행 시각을 쿼리로 붙여 매번 새 URL로 만든다
        from datetime import datetime
        link = f"{web}?v={datetime.now():%Y%m%d%H%M}"
    elif d.market == "KR":
        link = f"https://finance.naver.com/item/main.naver?code={d.ticker}"
    else:
        link = f"https://finance.yahoo.com/quote/{d.ticker}"
    return send_text("\n".join(lines), link, button_title="리포트 보기" if web else "자세히 보기")
