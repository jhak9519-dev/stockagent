# -*- coding: utf-8 -*-
"""
주간 AI 심층 리뷰 에이전트.

daily_review(규칙 기반 검산)와 달리, 이건 Claude가 최근 리포트들을 실제로 '읽고'
분석 품질·논리·서술·개선점을 심층 리뷰한다. 주 1회 실행(토큰 사용).

동작:
  1) 최근 N일(기본 7일)에 생성된 리포트 HTML을 텍스트로 추출
  2) Claude(llm)에게 리뷰어 역할로 개선점 도출 요청
  3) 결과를 output/reviews/<날짜>_weekly_review.md 로 저장 + 카톡/이메일 통지

사용:
  .venv\\Scripts\\python.exe tools\\weekly_ai_review.py [최근일수]
스케줄러: 주 1회(예: 일요일) 등록. 엔진은 .env LLM_PROVIDER(claude_code 권장).
"""
from __future__ import annotations

import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# 스케줄러(비로그인) 콘솔이 cp949라 이모지 출력 시 크래시 → stdout을 UTF-8로 강제
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stockagent.llm import llm  # noqa: E402

REVIEW_DIR = ROOT / "output" / "reviews"

SYSTEM = (
    "당신은 증권사 리서치센터의 리뷰 총괄(Chief Editor)입니다. "
    "AI가 자동 생성한 주식 리포트들을 감수해, 분석 품질·논리 정합성·서술·투자 유용성 관점에서 "
    "구체적이고 실행 가능한 개선점을 제시합니다. 칭찬보다 개선에 집중하되, 근거를 들어 균형 있게 씁니다."
)


def _extract(path: Path, limit: int = 4000) -> str:
    html = path.read_text(encoding="utf-8")
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
    return text[:limit]


def _recent_reports(days: int) -> list[Path]:
    cutoff = datetime.now() - timedelta(days=days)
    out = []
    for p in (ROOT / "output").rglob("*.html"):
        if "테스트전자" in p.name or "/reviews/" in p.as_posix():
            continue
        if datetime.fromtimestamp(p.stat().st_mtime) >= cutoff:
            out.append(p)
    return sorted(out, key=lambda p: p.stat().st_mtime, reverse=True)


def main() -> None:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    reports = _recent_reports(days)
    if not reports:
        print(f"최근 {days}일 내 리포트가 없습니다.")
        return
    if not llm.available:
        print("AI 엔진이 설정되지 않아 심층 리뷰를 건너뜁니다(LLM_PROVIDER 확인).")
        return

    blocks = []
    for p in reports[:7]:  # 최대 7건
        blocks.append(f"### 리포트: {p.name}\n{_extract(p)}")
    corpus = "\n\n".join(blocks)

    prompt = f"""아래는 최근 {days}일간 자동 생성된 주식 리포트 {len(reports)}건(발췌)입니다.
리서치센터 감수자 입장에서 심층 리뷰해 주세요.

{corpus}

다음 관점으로 **구체적 개선점**을 도출하세요(각 항목에 어느 리포트의 어떤 부분인지 근거 명시):
1. 분석 논리: 투자의견-목표가-근거-시나리오가 정합적인가? 비약·모순은?
2. 서술 품질: 진부한 표현 반복, 종목별 차별성 부족, 통찰 부재는 없는가?
3. 데이터 활용: 수집된 지표(수급·현금흐름·기술적)를 충분히 해석에 녹였는가?
4. 투자 유용성: 실제 투자자에게 실행 가능한 정보인가? 빠진 관점은?
5. 공통 패턴: 여러 리포트에 반복되는 약점(개선하면 전체가 좋아지는 것)

형식:
## 총평 (2~3문장)
## 개선점 (우선순위순, 각 항목: [무엇을] — [근거 리포트] — [어떻게 개선])
## 잘된 점 (간단히)
과장 없이, 실행 가능하게 작성하세요."""

    print(f"최근 {days}일 리포트 {len(reports)}건 심층 리뷰 중(AI)...")
    result = llm.ask(prompt, system=SYSTEM, max_tokens=3000, temperature=0.4)
    if not result or result.startswith("[AI"):
        print("AI 리뷰 생성 실패(엔진 응답 없음).")
        return

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REVIEW_DIR / f"{date.today()}_weekly_review.md"
    header = f"# StockAgent 주간 AI 심층 리뷰 ({date.today()})\n\n대상: 최근 {days}일 리포트 {len(reports)}건\n\n---\n\n"
    out_path.write_text(header + result, encoding="utf-8")
    print(f"✅ 저장: {out_path}")

    # 통지 (설정된 경우)
    try:
        from stockagent import notify
        if notify.enabled():
            notify.send_text(f"[StockAgent] 주간 AI 심층 리뷰 완료 ({len(reports)}건)\n"
                             "개선점은 output/reviews 폴더 또는 이메일 확인")
    except Exception:
        pass
    try:
        from stockagent import mailer
        if mailer.enabled():
            import os
            import smtplib
            import ssl
            from email.message import EmailMessage
            msg = EmailMessage()
            msg["Subject"] = f"[StockAgent] 주간 AI 심층 리뷰 {date.today()}"
            msg["From"] = f"StockAgent <{os.getenv('MAIL_SMTP_USER')}>"
            msg["To"] = os.getenv("MAIL_TO")
            msg.set_content(header + result)
            with smtplib.SMTP_SSL("smtp.naver.com", 465, context=ssl.create_default_context()) as s:
                s.login(os.getenv("MAIL_SMTP_USER"), os.getenv("MAIL_SMTP_PASS"))
                s.send_message(msg)
            print("✉ 이메일 발송 완료")
    except Exception as e:
        print(f"이메일 발송 건너뜀: {e}")


if __name__ == "__main__":
    main()
