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
set "GEN_ERR=%errorlevel%"
if not "%GEN_ERR%"=="0" echo [!] 리포트 생성 실패 (exit=%GEN_ERR%) - AI 엔진/네트워크/로그인 점검 필요>> "logs\scheduler_us.log"
REM 리포트 생성 직후 자동 점검(수치 검산·구조·폴백·오늘자 리포트 유무)
"%~dp0.venv\Scripts\python.exe" tools\daily_review.py >> "logs\scheduler_us.log" 2>&1
REM 스케줄러 결과창에 '리포트 생성'의 실제 성공/실패를 종료코드로 노출(성공으로 가려지지 않게)
exit /b %GEN_ERR%
