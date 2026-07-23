"""
이메일 발송 (네이버 SMTP) — 배치 리포트를 PDF 첨부로 메일 전송.

카톡 '나에게 보내기'(요약 알림)는 그대로 두고, 이메일은 리포트 PDF를 파일 그대로
받아보기 위한 별도 채널입니다. 여러 수신자에게도 보낼 수 있습니다(.env 쉼표 구분).

사전 준비(1회):
  1) 네이버 메일 > 환경설정 > POP3/IMAP 설정 > 'SMTP 사용' ON
  2) 2단계 인증 사용 시: 네이버 > 내정보 > 보안 > '애플리케이션 비밀번호' 발급
  3) .env 에 아래 3개 설정:
       MAIL_SMTP_USER=본인_네이버아이디@naver.com
       MAIL_SMTP_PASS=네이버_비밀번호_또는_앱비밀번호
       MAIL_TO=받는사람@naver.com   (여러 명이면 쉼표로 구분)
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from . import config  # noqa: F401  (.env 로드 보장 — 단독 import 시에도 키가 읽히도록)

_SMTP_HOST = "smtp.naver.com"
_SMTP_PORT = 465  # SSL


def enabled() -> bool:
    # 테스트(스모크) 실행 중에는 실제 메일을 보내지 않는다
    if os.getenv("STOCKAGENT_NO_PUBLISH"):
        return False
    return bool(os.getenv("MAIL_SMTP_USER") and os.getenv("MAIL_SMTP_PASS") and os.getenv("MAIL_TO"))


def _recipients() -> list[str]:
    return [a.strip() for a in os.getenv("MAIL_TO", "").split(",") if a.strip()]


def send_report_mail(report, file_path, log=print) -> bool:
    """리포트 요약을 본문에, PDF(또는 HTML)를 첨부해 메일 전송. 실패해도 배치를 막지 않음."""
    if not enabled():
        return False
    try:
        d, v = report.data, report.valuation
        cur = "₩" if d.market == "KR" else "$"

        def fmt(x):
            if x is None:
                return "-"
            return f"{x:,.0f}" if d.market == "KR" else f"{x:,.2f}"

        up = f" ({v.upside_pct:+.1f}%)" if (v and v.upside_pct is not None) else ""
        subject = f"[StockAgent] {d.name}({d.ticker}) {v.opinion} · 목표 {cur}{fmt(v.target_price)}{up}"

        lines = [
            f"■ 오늘의 종목: {d.name} ({d.ticker})",
            f"■ 투자의견: {v.opinion}",
            f"■ 목표가: {cur}{fmt(v.target_price)}{up}  /  현재가: {cur}{fmt(d.price)}",
        ]
        if getattr(v, "buy_low", None) and getattr(v, "buy_high", None):
            lines.append(f"■ 매수구간: {cur}{fmt(v.buy_low)} ~ {fmt(v.buy_high)}  /  손절: {cur}{fmt(v.stop_loss)}")
        if getattr(v, "strategy", ""):
            lines += ["", "■ 매매 전략", v.strategy]
        web = getattr(report, "web_url", None)
        if web:
            lines += ["", f"■ 웹 리포트: {web}"]
        lines += ["", "── 상세 내용은 첨부된 PDF를 확인하세요.",
                  "본 메일은 StockAgent가 자동 생성한 참고 자료이며 투자 권유가 아닙니다."]

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = f"StockAgent <{os.getenv('MAIL_SMTP_USER')}>"
        msg["To"] = ", ".join(_recipients())
        msg.set_content("\n".join(lines))

        p = Path(file_path)
        if p.exists():
            sub = "pdf" if p.suffix.lower() == ".pdf" else "octet-stream"
            msg.add_attachment(p.read_bytes(), maintype="application", subtype=sub, filename=p.name)

        with smtplib.SMTP_SSL(_SMTP_HOST, _SMTP_PORT, context=ssl.create_default_context()) as s:
            s.login(os.getenv("MAIL_SMTP_USER"), os.getenv("MAIL_SMTP_PASS"))
            s.send_message(msg)
        log(f"  ✉ 이메일 발송 완료: {', '.join(_recipients())}")
        return True
    except Exception as e:
        log(f"  ⚠ 이메일 발송 실패(리포트는 정상 저장됨): {e}")
        return False
