# -*- coding: utf-8 -*-
"""
일일 리포트 점검 에이전트.

매일 배치가 리포트를 생성한 뒤, 가장 최근 리포트를 자동으로 검산·점검한다.
Claude 호출 없이 '규칙으로 확실히 검증 가능한 항목'만 확인하고, 이상이 발견되면
logs/daily_review.log 에 기록하고 (알림 설정 시) 카톡/이메일로 통지한다.

점검 항목(report-review 스킬의 자동 검증 가능 부분):
  · 상승여력 = 목표가/현재가 − 1 (표기 일치)
  · 목표주가 산출식 = 지표 × 배수 (계산 일치)
  · 매수구간 상단 < 현재가 (현재가 추격매수 금지 — 사용자 확정 기준)
  · 시나리오 확률 합 = 100%
  · AI 폴백 발생 여부("규칙 기반 자동 요약")
  · 대화체·제안 문구 유입("해드릴까요" 등)
  · 필수 섹션 존재(차트분석·수급·밸류에이션·매매전략)

사용:
  .venv\\Scripts\\python.exe tools\\daily_review.py [리포트.html]
  (생략 시 output 하위 가장 최근 HTML 자동 선택)
스케줄러/배치에서 리포트 생성 직후 호출하면 매일 자동 점검된다.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

# 스케줄러(비로그인) 콘솔이 cp949라 이모지 출력 시 크래시 → stdout을 UTF-8로 강제
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LOG = ROOT / "logs" / "daily_review.log"


def _latest_html() -> Path | None:
    cands = [p for p in (ROOT / "output").rglob("*.html") if "테스트전자" not in p.name]
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except Exception:
        return None


def review(path: Path) -> list[str]:
    """리포트 HTML을 검산해 발견된 문제 목록을 반환(빈 리스트면 이상 없음)."""
    html = path.read_text(encoding="utf-8")
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    issues: list[str] = []

    price = _num((re.search(r"현재가\s*[₩$]?([\d,]+\.?\d*)", text) or [None, None])[1])

    # 1) 상승여력 검산
    tgt = _num((re.search(r"목표주가 [₩$]?([\d,]+\.?\d*)", text) or [None, None])[1])
    up = re.search(r"상승여력\s*([+\-][\d.]+)%", text)
    if tgt and price and up:
        calc = (tgt / price - 1) * 100
        if abs(calc - float(up.group(1))) > 0.3:
            issues.append(f"상승여력 불일치: 표기 {up.group(1)}% vs 계산 {calc:+.1f}%")

    # 2) 목표주가 산출식 검산
    fm = re.search(r"([\d,]+\.?\d*)\s*[원달러$]*\s*×\s*타깃 \w+ ([\d.]+)배\s*=\s*목표주가 ([\d,]+\.?\d*)", text)
    if fm:
        base, mult, res = _num(fm.group(1)), _num(fm.group(2)), _num(fm.group(3))
        if base and mult and res and abs(base * mult - res) / res > 0.01:
            issues.append(f"목표가 산출식 불일치: {base:,.0f}×{mult} ≠ {res:,.0f}")

    # 3) 매수구간 상단 < 현재가
    bz = re.search(r"매수 희망 구간[^0-9]*[₩$]?([\d,]+\.?\d*)\s*~\s*[₩$]?([\d,]+\.?\d*)", text)
    if bz and price:
        hi = _num(bz.group(2))
        if hi and hi > price * 1.001:
            issues.append(f"매수구간 상단({hi:,.0f})이 현재가({price:,.0f})보다 높음 — 추격매수 위험")

    # 4) 시나리오 확률 합
    probs = re.findall(r"(?:강세|기본|약세)[^%]*?(\d+)%", text)
    if len(probs) >= 3:
        total = sum(int(p) for p in probs[:3])
        if total != 100:
            issues.append(f"시나리오 확률 합 {total}% (100이어야 함)")

    # 5) AI 폴백 / 대화체
    if "규칙 기반 자동 요약" in text:
        issues.append("AI 폴백 발생(규칙 기반 자동 요약) — 엔진 인증/한도 확인 필요")
    if re.search(r"해드릴까요|드리겠습니다만|말씀해\s*주세요", text):
        issues.append("대화체·제안 문구 유입(claude_code guard 확인)")

    # 6) 필수 섹션 존재
    for sec in ("차트 분석", "수급 동향", "밸류에이션", "매매 전략"):
        if sec not in text:
            issues.append(f"필수 섹션 누락: {sec}")

    # 7) 실적 발표 예정일이 발행일보다 과거면 오표기 (리뷰 #3b)
    em = re.search(r"실적 발표\(예정\)\s*(\d{4}-\d{2}-\d{2})", text)
    fn = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    if em and fn and em.group(1) < fn.group(1):
        issues.append(f"실적 발표 예정일({em.group(1)})이 발행일({fn.group(1)})보다 과거")

    # 8) 시나리오 표 누락 (리뷰 #10)
    if "12개월 목표가" not in html:
        issues.append("시나리오 표 누락(강세/기본/약세)")

    return issues


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else _latest_html()
    if not path or not path.exists():
        print("점검할 리포트를 찾을 수 없습니다.")
        return

    issues = review(path)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        if issues:
            f.write(f"\n[{stamp}] ⚠ {path.name} — {len(issues)}건\n")
            for i in issues:
                f.write(f"  - {i}\n")
        else:
            f.write(f"[{stamp}] ✅ {path.name} — 이상 없음\n")

    if issues:
        print(f"⚠ {path.name}: {len(issues)}건 발견")
        for i in issues:
            print("  -", i)
        # 이상 발견 시 알림(설정된 경우에만)
        try:
            from stockagent import notify
            if notify.enabled():
                notify.send_text(f"[StockAgent] ⚠ 리포트 점검 이상 {len(issues)}건\n"
                                 + "\n".join("· " + i[:40] for i in issues[:4]))
        except Exception:
            pass
    else:
        print(f"✅ {path.name}: 이상 없음")


if __name__ == "__main__":
    main()
