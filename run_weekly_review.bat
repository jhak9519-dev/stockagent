@echo off
REM 주간 AI 심층 리뷰 (스케줄러가 주 1회 호출) — 최근 7일 리포트를 Claude가 감수
chcp 65001 >nul
cd /d "%~dp0"
REM --- 비로그인(S4U) 실행 대비: 사용자 프로파일 환경 명시 ---
set "USERPROFILE=C:\Users\admin"
set "APPDATA=C:\Users\admin\AppData\Roaming"
set "LOCALAPPDATA=C:\Users\admin\AppData\Local"
set "PATH=C:\Users\admin\.local\bin;%PATH%"
set "PYTHONIOENCODING=utf-8"
set "LLM_PROVIDER=claude_code"
if not exist logs mkdir logs
echo ===================== weekly AI review  %date% %time% =====================>> "logs\weekly_review.log"
"%~dp0.venv\Scripts\python.exe" tools\weekly_ai_review.py 7 >> "logs\weekly_review.log" 2>&1
