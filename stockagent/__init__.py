"""Stock Agent — 멀티 에이전트 주식 리서치 보고서 생성 시스템."""

import sys as _sys

__version__ = "0.1.0"

# Windows 콘솔 기본 인코딩(cp949)에서 한글/이모지 출력이 깨지지 않도록 UTF-8로 전환.
for _stream in (_sys.stdout, _sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # Python 3.7+
    except Exception:
        pass
