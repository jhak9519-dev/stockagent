# Stock Agent — 멀티 에이전트 주식 리서치 보고서 생성기

공개된 시세·재무 데이터를 바탕으로, 여러 AI 에이전트가 협업하여
**증권사 리포트 형식의 리포트(PDF·웹)** 를 자동 생성하고, **카톡·이메일·웹**으로 발송합니다.
한국(KOSPI/KOSDAQ)과 미국(S&P500 + 나스닥100)을 지원하며, 실제 매매는 하지 않습니다.

> ⚠️ 본 시스템의 산출물은 **투자 참고용 자동 생성 자료**이며, 매매 권유가 아닙니다.
> 투자 판단과 책임은 전적으로 투자자 본인에게 있습니다.

---

## 1. 전체 구조 (멀티 에이전트 파이프라인)

리서치센터가 일하는 방식을 소프트웨어 에이전트로 나눴습니다. 각 에이전트는 한 가지 역할만 맡습니다.

| 단계 | 에이전트 | 하는 일 | AI 사용 |
|---|---|---|---|
| ① | **스크리너** (`agents/screener.py`) | 종목 풀을 추세·모멘텀 지표로 채점해 후보 압축 (US=S&P500∪나스닥100 518종목 일괄) | ✗ (규칙) |
| ② | **데이터 수집** (`datasources/`) | 시세·재무제표·뉴스·컨센서스·수급·기술적 지표 (DART·FDR·yfinance·네이버·judal) | ✗ |
| ③ | **재무 분석가** (`agents/fundamental.py`) | 성장성·수익성·안정성·현금흐름 해석 | ✓ Claude |
| ④ | **시황 분석가** (`agents/market.py`) | 주가 흐름·업종·수급·뉴스 + 차트 관점 전망 | ✓ Claude |
| ⑤ | **밸류에이션** (`agents/valuation.py`) | 투자의견·목표주가·시나리오·매매전략 | ✓ Claude |
| ⑥ | **보고서 작성가** (`agents/writer.py`) | 투자 요약(Thesis) 종합 서술 | ✓ Claude |
| ⑦ | **렌더러·발송** (`report/`, `notify.py`, `mailer.py`) | 차트+HTML→PDF, 웹 발행, 카톡·이메일 발송 | ✗ |

전체 조율은 `orchestrator.py`(팀장 역할)가 담당합니다.

### 리포트에 담기는 내용
투자의견·매수구간·목표주가·손절가·상승여력 | 투자요약 | 시황(거시·업종·수급) | **차트 분석**(일목균형표·볼린저·이동평균·RSI·MACD, 추세강도 n/10, 지지·저항) | **수급 동향**(KR=개인/외국인/기관/연기금 일별, US=기관·공매도·일별 주가/거래량) | 재무(현금흐름 포함) | **밸류에이션**(목표가 산출식·시나리오 확률·기대값·리스크/리워드·컨센서스) | **매매 전략**(추세 기반) | 리스크 | 증권사 리포트·뉴스

---

## 2. 설치 (최초 1회)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium      # PDF 렌더용 브라우저 엔진
```

### API 키 설정 (`.env`)
`.env.example` 을 복사해 `.env` 로 저장한 뒤 채웁니다.

| 키 | 용도 | 필수 |
|---|---|---|
| `LLM_PROVIDER` | AI 엔진: `claude_code`/`claude`/`gemini`/`auto`/`rule` | — |
| `ANTHROPIC_API_KEY`·`ANTHROPIC_MODEL` | Claude API 사용 시 | 선택 |
| `GEMINI_API_KEY`·`GEMINI_MODEL` | Gemini 무료 티어 사용 시 | 선택 |
| `DART_API_KEY` | 한국 재무제표(DART, 무료) | KR 권장 |
| `KAKAO_REST_API_KEY`·`KAKAO_CLIENT_SECRET`·`KAKAO_REFRESH_TOKEN` | 카톡 알림 | 선택 |
| `MAIL_SMTP_USER`·`MAIL_SMTP_PASS`·`MAIL_TO` | 이메일 발송(네이버 SMTP) | 선택 |

**AI 엔진 선택:**
| `LLM_PROVIDER` | 엔진 | 비용 | 준비물 |
|---|---|---|---|
| `claude_code` | **Claude Code (구독)** | 구독 포함 | Claude Code 로그인 — **API 키 불필요, 스케줄러 기본값** |
| `claude` | Claude API | 종량제 | console.anthropic.com 키 |
| `gemini` | Gemini | 무료~ | aistudio.google.com/apikey 키 |
| `rule` | 규칙 기반 | 무료 | 없음 |

> AI 키가 없어도 실행됩니다(규칙 기반 요약). 키를 넣으면 AI 서술로 자동 교체됩니다.
> 각 발송 채널(카톡·이메일)은 키가 설정된 경우에만 동작하고, 없으면 조용히 건너뜁니다.

---

## 3. 사용법

```powershell
python run.py --best                    # ⭐ 한·미 통합 최유망 1종목
python run.py --best --market KR         # 한국 1종목 (장 마감 후)
python run.py --best --market US         # 미국 1종목
python run.py --market KR --top 3        # 한국 상위 3종목 자동발굴
python run.py --market KR --tickers 005930 000660   # 특정 종목 지정
python run.py --watchlist               # 관심종목 전체 → output/watchlist/
```

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `--best` | 한·미 통합 스크리닝 후 가장 유망한 1종목만 | — |
| `--market` | `KR` 또는 `US` | (best는 통합) |
| `--top` | 자동 발굴 보고서 수 | `3` |
| `--pool` | 스크리닝 후보풀 크기 | `40` |
| `--tickers` | 특정 종목코드 (스크리닝 생략) | 없음 |
| `--watchlist` | 관심종목(watchlist.txt) 전체 | — |

- **디자인만 수정 시**: `python tools/rerender_pdf.py <리포트.html>` — AI 재분석 없이 PDF 재생성(CSS/레이아웃 변경만 반영).
- **관심종목**: `watchlist.txt`에 `시장 종목코드 메모` 형식으로 편집. 자동발굴 종목은 끝에 자동 누적(중복 제외).

---

## 4. 발송 채널 & 웹 리포트

배치가 리포트를 생성하면 아래 3곳으로 자동 발송됩니다(설정된 채널만).

| 채널 | 내용 |
|---|---|
| **카톡** (`notify.py`) | '나에게 보내기'로 핵심 요약 1건 + [리포트 보기] 버튼(웹 리포트 연결) |
| **이메일** (`mailer.py`) | 요약 본문 + **PDF 첨부** (네이버 SMTP, `MAIL_TO`에 쉼표로 다수 수신 가능) |
| **웹** (`report/publish.py`) | GitHub Pages 발행 → https://jhak9519-dev.github.io/stock-reports/ (다크 테마) |

- 웹 목록/리포트에는 **발행 매수가 대비 현재 수익률**(수익 빨강/손실 파랑)과 **주간·월간·전체 평균 수익률**이 표시되며, 배치가 돌 때마다 최신 현재가로 갱신됩니다.
- 발굴 이력이 쌓이면 리포트 헤더에 **"발굴 누적 N회 · M회 연속"** 배지가 붙습니다.

---

## 5. 폴더 구조

```
StockAgent/
├─ run.py                    # 실행 진입점 (CLI)
├─ run_all.bat               # 전체 한 번에 실행 (더블클릭)
├─ run_kr_best.bat / run_us_best.bat   # 스케줄러용 (Claude Code 엔진)
├─ watchlist.txt             # 관심종목 목록 (직접 편집)
├─ .env                      # API 키 (직접 생성, 커밋 금지)
├─ tools/
│  ├─ kakao_auth.py          # 카카오 토큰 최초 발급 (1회)
│  └─ rerender_pdf.py        # 디자인만 수정 시 PDF 재렌더 (AI 불필요)
├─ stockagent/
│  ├─ config.py · models.py · llm.py · orchestrator.py · watchlist.py
│  ├─ history.py             # 발굴 이력(누적·연속)
│  ├─ notify.py · mailer.py  # 카톡 · 이메일 발송
│  ├─ datasources/           # kr.py, us.py, news.py, flows.py, technical.py
│  ├─ agents/                # screener/fundamental/market/valuation/writer/rule_based, context.py
│  └─ report/                # charts.py, html_builder.py, pdf.py, publish.py, templates/
├─ web/                      # GitHub Pages 발행 폴더 (별도 git 저장소)
├─ cache/                    # dart_corp_map, pick_history.json
└─ output/<날짜>/            # 생성된 PDF·HTML (관심종목은 output/watchlist/<날짜>/)
```

---

## 6. 자동 실행 (스케줄러)

| 작업 이름 | 실행 시각(KST) | 하는 일 |
|---|---|---|
| `StockAgent_KR_Best` | 평일 **15:40** | 한국장 마감 후 한국 최유망 1종목 |
| `StockAgent_US_Best` | 화~토 **06:30** | 미국장 마감 후 미국 최유망 1종목 |
| `StockAgent_Weekly_Review` | 월요일 **08:30** | 최근 7일 리포트 **AI 심층 리뷰**(개선점 도출) — 토요일 US 배치(금요일장)까지 반영 |

- 미국장 마감(16:00 ET ≈ 한국 새벽)이라 다음날 06:30 실행.
- **로그인 무관 실행(S4U) + 최고 권한**으로 등록돼, 잠금·미로그인 상태에서도 백그라운드로 실행됩니다(완전 종료 시엔 미실행 → 이후 부팅 시 실행).
- 로그: `logs\scheduler_kr.log` / `scheduler_us.log`

```powershell
Get-ScheduledTask StockAgent_* | Get-ScheduledTaskInfo | ft TaskName, NextRunTime, LastRunTime, LastTaskResult
Start-ScheduledTask -TaskName StockAgent_KR_Best      # 즉시 실행
```

---

## 7. 한계와 주의

- 무료 데이터 소스 기반이라 실시간성이 낮고 일부 지표가 비어 있을 수 있습니다.
- **미국은 투자자 유형별(개인/외국인/기관) 일별 매매가 공개되지 않아**, 수급을 기관·내부자 보유율·공매도·일별 주가/거래량으로 갈음합니다(한국만 투자자별 순매수 제공).
- 웹 리포트는 **공개** GitHub Pages입니다(URL을 알면 접근 가능). 비공개 전환 시 무료 플랜에서는 웹이 중단됩니다.
- AI 서술은 제공된 데이터 범위 내 해석이며, 미래 주가를 보장하지 않습니다.

---

## 8. 변경 이력 (Changelog)

> 리포트·기능을 수정할 때마다 최신순으로 여기에 기록합니다.

### 2026-07-27 — 무인 배치 장애 복구 + 실패 감지 하드닝
- **증상**: 07-24~26 정기 배치가 "성공(0x0)"으로 표시됐으나 실제 리포트는 미생성. 원인 2가지 —
  (A) 무인(S4U) 세션에서 AI 엔진(`claude -p`)이 응답 못 함(로그인 토큰 갱신 이슈, 주간리뷰 로그의 180초 타임아웃) → 재로그인으로 해소,
  (B) `.bat` 줄바꿈이 LF로 저장돼 `cmd.exe`가 오파싱(1초 만에 종료) → **CRLF로 복구**.
- **실패가 4일간 안 보인 이유**: `.bat`이 `리포트생성 → daily_review` 순서라 종료코드가 마지막 명령(daily_review) 기준 → 생성 실패가 초록불로 가려짐.
- **하드닝**:
  - `run_kr_best.bat`/`run_us_best.bat`: 리포트 생성 결과를 `exit /b`로 스케줄러에 노출(성공 위장 방지)
  - `daily_review.py`: '오늘자 리포트 없음'(=배치 실패) 감지 시 카톡 경고
  - `llm.py`: AI 호출 실패 원인을 `logs/llm_errors.log`에 영구 기록(무인 stdout 유실 대비)
  - `notify.py`: `STOCKAGENT_NO_PUBLISH` 시 알림 미발송(진단 실행 안전)
  - `.gitattributes` 추가: `*.bat`을 CRLF로 고정해 LF 손상 재발 방지
- 무인(S4U) 실제 실행으로 웹 발행·이메일·카톡까지 전 과정 정상 검증 완료

### 2026-07-27 — 과거 리포트에 새 표 디자인 일괄 적용
- **과거분 재생성 도구 추가**(`tools/rerender_design.py`): AI 재분석 없이 옛 리포트의 `<style>`를 최신본으로 교체하고, 저항선/지지선(줄바꿈)·일자별 수급표(colgroup)·시나리오 표(핵심조건 55%)를 새 마크업으로 업그레이드. output HTML 재작성+PDF 재렌더 후, 웹 발행본은 실제 발행 파이프라인(`_mobilify`)에 통과시켜 신규 리포트와 동일한 다크 테마로 재생성
- 과거 리포트 12건(2026-07-16~23) 전부 재생성·웹 재발행 완료
- **웹 다크 버그 수정**: 시나리오 핵심 조건(`.cond`)이 다크 배경에서 어둡게(#444) 나오던 문제 → 웹 스타일에 밝은색(#b9c2d0) 오버라이드 추가(신규 리포트에도 적용)

### 2026-07-23 (밤 2) — 표 가독성 개선
- **표 칸 폭을 글자 수에 맞게 조정**: 항목명(키) 칸을 22% 고정에서 내용 길이만큼 축소(`white-space:nowrap; width:1%`)하고 값 칸이 남는 폭을 차지하도록 변경 → 밸류에이션·수급·기술적 표의 여백 낭비 해소
- **한 칸의 여러 항목을 줄바꿈 분리**: 저항선/지지선의 여러 레벨을 ` · ` 나열 대신 각 줄로(`<br>`) 표시. 외국인 순매수는 금액과 보유율을 두 줄로 분리(보유율은 회색)
- **일자별 수급현황표 폭 배분**: `colgroup`으로 일자·종가·등락률·개인·외국인·기관(KR)/거래량(US) 칸을 글자 수 비율대로 고정하고 숫자는 우측정렬, 날짜는 가운데정렬
- **시나리오 표 재배분**: 핵심 조건 칸을 55%로 넓히고 시나리오·목표가·확률 칸을 좁혀(15/19/11/55) 주 내용이 잘 읽히도록 개선
- 웹(다크)·PDF 양쪽 검증 완료(`tests/smoke_render.py`에 기술적 지표·일자별 수급·시나리오 mock 추가)

### 2026-07-23 (밤)
- **daily_review·weekly_ai_review 인코딩 버그 수정**: 스케줄러(cp949 콘솔)에서 이모지 출력 시 크래시 → stdout을 UTF-8로 강제(`sys.stdout.reconfigure`). 배치 본체는 정상이었으나 이 크래시로 종료코드가 1로 잡히던 문제 해결
- **차트 다크 테마**: 주가·재무 차트를 웹 카드색(#141b24) 배경·밝은 색으로 → 웹 다크 페이지와 조화(`charts._style_dark`). PDF에선 어두운 차트 박스로 표시
- **BOM 이슈 수정**: json 읽기를 `utf-8-sig`로(BOM 있어도 파싱) + 기존 manifest·pick_history·report_history BOM 제거

### 2026-07-23 (저녁) — 주간 AI 리뷰 잔여 3건
- **#8 스크리너 점수 개편**: 모멘텀 기여 상한 클램프(±25/±15)·과열 감점 강화·20일선 과이격·탄력 둔화 감점 → 급등주 편중 해소(저변동 종목도 후보 진입). ETF 브랜드(KODEX·TIGER 등) 필터 보강
- **#7 ATR 변동성 손절**: 일률 −5% → 종목 변동성(ATR14) 기반 5~12%
- **#6 전일 대비 변경 고지**: 같은 종목 재발행 시 헤더에 목표가·의견 변경 요약(`cache/report_history.json`)

### 2026-07-23 (오후) — 주간 AI 리뷰 반영 + 데이터소스 전환
- **네이버 기반 전환**(`datasources/naver_kr.py`): fdr의 KR 상장목록·시총 소스가 404 장애 → 네이버 증권 시총 랭킹(유니버스)·개별 지표(시총·PER·PBR·EPS·BPS·배당·52주)로 대체. DART 재무·업종은 유지. 시총-주가 정합성·지표 정확도 개선
- **주간 AI 리뷰 지적 10건 수정**: 목표가 배수 컨센서스 클램프(±35%)·배수 앵커 프롬프트, 진입 태도 표기(즉시/조정 시/관심 진입 레벨), 실적일 미래 필터, 매수구간 각주 동적화, 점수 등급(유망/관찰/참고), 종목 고유 논점 의무화, 지주사 NAV 밸류 가이드, 12개월 목표 명시, 시나리오 3개 필수, daily_review 검산 추가
- `.claude/settings.json` autoCompactEnabled 명시

### 2026-07-23 (오전)
- **README.md 전면 개편** — 발송 채널·웹·수익률·자동화 반영, 이후 모든 변경을 이 Changelog에 기록
- 재무 지표 표에 **영업현금흐름·잉여현금흐름(FCF) 행 추가** (KR=DART 영업CF, US=yfinance 영업CF+FCF)
- **watchlist.txt 국장(KR)/미장(US) 섹션 구분** — 자동 발굴 종목도 해당 시장 섹션에 정리(`watchlist.regroup()`으로 기존분 재정렬)
- **일일 점검 에이전트 `tools/daily_review.py`** — 배치 직후 리포트 자동 검산(상승여력·산출식·매수구간 상단·시나리오 확률합·폴백·대화체·필수 섹션). 이상 시 `logs/daily_review.log` 기록 + 카톡 알림. 스케줄러 bat에 연결됨
- **주간 AI 심층 리뷰 `tools/weekly_ai_review.py`** — Claude가 최근 7일 리포트를 감수해 개선점 도출 → `output/reviews/<날짜>_weekly_review.md` + 이메일. 스케줄러 `StockAgent_Weekly_Review`(일요일 09:00) 등록
- 리포트 상세 헤더에 **매수가 대비 수익률 배지** 추가 (목록 갱신 시 전 상세 자동 최신화, 기존 리포트 소급)
- **국내↔미국 리포트 일관성 점검 완료** — 모든 개선사항(블록 레이아웃·수익률 배지·시나리오·매매전략·차트분석·현금흐름·일별표 부호색 등)이 양 시장에 공통 적용됨을 확인. KR 전용(개인/외국인/기관·연기금)과 US 전용(기관/내부자 보유·공매도·실적발표일)은 각 시장 데이터 특성에 따른 차이(누락 아님)

### 2026-07-22
- 목록: **주간·월간·전체 평균 수익률** 요약 박스, 종목별 **매수가 대비 수익률 배지**(수익 빨강/손실 파랑, 기존분 소급)
- 웹 발행본 **다크 카드 레이아웃**(주제별 블록 카드, 여백 확대, 키워드 칩)
- **발굴 이력 배지**("누적 N회 · M회 연속", `history.py`)
- 미국 종목 **일별 표**(주가·등락률·거래량)

### 2026-07-21
- **수급 일별 표**(7거래일): KR 개인/외국인/기관 순매수 + 종가·등락률, 부호색(상승/순매수 빨강·하락/순매도 파랑)
- **PDF 페이지 자연 흐름**(짧은 섹션 합치고 넘치면 새 페이지)
- **매매전략 AI 판단** 전환(추세강도별 차등, 획일적 표현 제거)
- **이메일 발송**(네이버 SMTP, PDF 첨부)
- 리포트 분량 축소, 빠른 재렌더 도구(`tools/rerender_pdf.py`)

### 2026-07-20
- **벤치마킹 개선**: 시나리오 분석(강세/기본/약세+확률+가중 기대값), 리스크/리워드, 추세강도 점수, 지지·저항 표, 현금흐름(영업CF·FCF), 분할매수 가이드
- 미국 유니버스 확장 **S&P500 + 나스닥100**(518종목)
- 연기금 순매수 표시(judal.co.kr)

### 2026-07-16
- 스케줄러 안정화(**로그인 무관 실행 S4U**, 업데이트 활성시간, 운영 로그)
- 미국 스크리너 버그 수정(알파벳순 40 → 전체 채점)
- 리포트: 목표주가 산출식·BPS·과열 배지·선정 근거·통화 표기 / 데이터: 적자 PER·KR 업종·뉴스 중복·US 실적일
- **GitHub Pages 웹 발행** + 카톡 알림([리포트 보기] 버튼)

### ~2026-07-15 (초기 구축)
- 멀티 에이전트 파이프라인, 한국(FDR+DART)·미국(yfinance), Claude/Gemini/규칙기반 엔진
- 매수구간·손절가, 컨센서스, 증권사 리포트·뉴스, 차트, HTML→PDF
