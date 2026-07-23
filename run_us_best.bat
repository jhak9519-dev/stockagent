@echo off
REM 미국장 마감 후 실행용: 미국 주식 중 최유망 1종목 리포트 (스케줄러가 호출)
chcp 65001 >nul
cd /d "%~dp0"
REM --- 비로그인(스케줄러 S4U) 실행 대비: 사용자 프로파일 환경을 명시 ---
REM  S4U 세션은 사용자 PATH/프로파일 변수를 로드하지 않아 claude CLI·인증·Chromium을 못 찾음
set "USERPROFILE=C:\Users\admin"
set "APPDATA=C:\Users\admin\AppData\Roaming"
set "LOCALAPPDATA=C:\Users\admin\AppData\Local"
set "PATH=C:\Users\admin\.local\bin;%PATH%"
set "PYTHONIOENCODING=utf-8"
REM AI 엔진: Claude Code 구독 사용 (API 키 불필요)
set "LLM_PROVIDER=claude_code"
if not exist logs mkdir logs
echo ===================== US best  %date% %time% =====================>> "logs\scheduler_us.log"
"%~dp0.venv\Scripts\python.exe" run.py --best --market US >> "logs\scheduler_us.log" 2>&1
REM 리포트 생성 직후 자동 점검(수치 검산·구조·폴백)
"%~dp0.venv\Scripts\python.exe" tools\daily_review.py >> "logs\scheduler_us.log" 2>&1
