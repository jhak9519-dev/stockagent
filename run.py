"""
Stock Agent 실행 스크립트 (수동 실행).

사용 예:
  # 한국 시장 자동 발굴 (상위 3종목 보고서)
  python run.py --market KR --top 3

  # 미국 시장 자동 발굴
  python run.py --market US --top 3

  # 특정 종목만 분석 (스크리닝 건너뜀 · 빠른 테스트)
  python run.py --market KR --tickers 005930 000660
  python run.py --market US --tickers AAPL MSFT

  # '가장 유망한 1종목'만 리포트 (AI 호출 최소 → 무료티어 권장)
  python run.py --best                 # 한·미 통합에서 1종목
  python run.py --best --market KR     # 한국 안에서 1종목 (한국장 마감 후용)
  python run.py --best --market US     # 미국 안에서 1종목 (미국장 마감 후용)

  # 관심종목(watchlist.txt) 전체 리포트 (output/watchlist/ 에 별도 저장)
  python run.py --watchlist

옵션:
  --best                        가장 유망한 1종목만 분석 (--market 없으면 한·미 통합)
  --market    KR | US           분석할 시장 (자동발굴 기본 KR)
  --top       N                 자동 발굴 시 보고서를 만들 상위 종목 수 (기본 3)
  --pool      N                 스크리닝 후보풀 크기 (클수록 정확하지만 느림, 기본 40)
  --tickers   ...               특정 종목코드들 (지정 시 스크리닝 생략)
  --watchlist                   watchlist.txt 의 관심종목 전체를 분석 (다른 옵션 무시)
"""
from __future__ import annotations

import argparse

from stockagent.orchestrator import run, run_best, run_watchlist


def main() -> None:
    parser = argparse.ArgumentParser(description="멀티 에이전트 주식 리서치 보고서 생성기")
    parser.add_argument("--best", action="store_true", help="가장 유망한 1종목만 분석 (--market 없으면 한·미 통합)")
    parser.add_argument("--market", choices=["KR", "US"], default=None, help="분석 시장 (자동발굴 기본 KR)")
    parser.add_argument("--top", type=int, default=3, help="자동 발굴 보고서 수 (기본 3)")
    parser.add_argument("--pool", type=int, default=40, help="스크리닝 후보풀 크기 (기본 40)")
    parser.add_argument("--tickers", nargs="*", default=None, help="특정 종목코드 (지정 시 스크리닝 생략)")
    parser.add_argument("--watchlist", action="store_true", help="관심종목(watchlist.txt) 전체 분석")
    args = parser.parse_args()

    try:
        if args.best:
            run_best(market=args.market, pool_size=args.pool)
            return

        if args.watchlist:
            run_watchlist()
            return

        run(
            market_choice=args.market or "KR",
            top_n=args.top,
            pool_size=args.pool,
            explicit_tickers=args.tickers,
        )
    except Exception as e:
        # 무인(스케줄러) 실행 중 실패를 카톡으로 즉시 알림 — 알림 실패는 무시
        try:
            from stockagent import notify
            if notify.enabled():
                notify.send_text(f"[StockAgent] ❌ 배치 실패: {type(e).__name__}: {str(e)[:120]}")
        except Exception:
            pass
        raise  # 원래 오류는 그대로 로그에 남긴다


if __name__ == "__main__":
    main()
