@echo off
REM ============================================================
REM  Stock Agent - 전체 리포트 한 번에 생성 (더블클릭 실행)
REM   1) 관심종목(watchlist)   2) 한국 top5   3) 미국 top5
REM  나중에 자동화하려면 Windows 작업 스케줄러에서 이 파일을 지정하세요.
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"

echo.
echo [1/3] 관심종목(watchlist) 리포트 생성...
"%PY%" run.py --watchlist

echo.
echo [2/3] 한국 유망종목 top5 자동발굴...
"%PY%" run.py --market KR --top 5

echo.
echo [3/3] 미국 유망종목 top5 자동발굴...
"%PY%" run.py --market US --top 5

echo.
echo ============================================================
echo  전체 완료! output\날짜 폴더(관심종목은 output\watchlist\날짜)를 확인하세요.
echo ============================================================
pause
