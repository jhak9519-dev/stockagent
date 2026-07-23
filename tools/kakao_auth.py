# -*- coding: utf-8 -*-
"""
카카오 토큰 최초 발급 도구 (1회만 실행).

실행:  .venv\\Scripts\\python.exe tools\\kakao_auth.py

동작 순서(비개발자 설명):
  1) 브라우저가 자동으로 열리고 카카오 로그인 화면이 나옵니다.
  2) 로그인 후 [동의하고 계속하기]를 누르면, 카카오가 이 PC(localhost:8899)로
     '인증 코드'를 돌려보냅니다. 스크립트가 그 코드를 받아서
  3) access/refresh 토큰으로 교환한 뒤 .env 에 자동 저장하고,
  4) 확인용 카톡 1건을 '나와의 채팅'으로 보내봅니다.

사전 준비: developers.kakao.com 앱의
  - REST API 키가 .env 의 KAKAO_REST_API_KEY 에 있어야 하고(없으면 입력을 물어봄)
  - 카카오 로그인 Redirect URI 에 http://localhost:8899/callback 이 등록되어 있어야 하며
  - 동의항목에서 '카카오톡 메시지 전송(talk_message)' 이 켜져 있어야 합니다.
"""
from __future__ import annotations

import http.server
import os
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from stockagent import notify  # noqa: E402  (.env 로드는 stockagent.config 가 수행)

PORT = 8899
REDIRECT_URI = f"http://localhost:{PORT}/callback"
AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"


def main() -> None:
    print("=" * 60)
    print(" 카카오톡 알림 - 최초 인증 (1회)")
    print("=" * 60)

    rest_key = os.getenv("KAKAO_REST_API_KEY", "").strip()
    if not rest_key:
        rest_key = input("카카오 REST API 키를 붙여넣고 Enter: ").strip()
        if not rest_key:
            print("REST API 키가 없어 중단합니다.")
            return
        notify._update_env("KAKAO_REST_API_KEY", rest_key)
        print("  → .env 에 KAKAO_REST_API_KEY 저장 완료")

    # ── 인증 코드를 받을 임시 로컬 서버 ──────────────────────────
    got = {"code": None, "error": None}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if "code" in params:
                got["code"] = params["code"]
                msg = "인증 완료! 이 창을 닫고 터미널로 돌아가세요."
            else:
                got["error"] = params.get("error_description") or str(params)
                msg = f"인증 실패: {got['error']}"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<h2>{msg}</h2>".encode("utf-8"))
            done.set()

        def log_message(self, *args):  # 콘솔 잡음 제거
            pass

    server = http.server.HTTPServer(("localhost", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # ── 브라우저에서 카카오 로그인 ──────────────────────────────
    url = (
        f"{AUTH_URL}?client_id={rest_key}&redirect_uri={REDIRECT_URI}"
        "&response_type=code&scope=talk_message"
    )
    print("\n브라우저가 열립니다. 카카오 로그인 후 [동의하고 계속하기]를 눌러주세요.")
    print(f"(자동으로 안 열리면 이 주소를 브라우저에 붙여넣기: {url})\n")
    webbrowser.open(url)

    if not done.wait(timeout=300):
        print("⏱ 5분 내에 인증이 완료되지 않아 중단합니다. 다시 실행해 주세요.")
        return
    server.shutdown()
    if got["error"]:
        print(f"✗ 인증 실패: {got['error']}")
        print("  → Redirect URI 등록(http://localhost:8899/callback)과 동의항목(talk_message)을 확인하세요.")
        return

    # ── 인증 코드 → 토큰 교환 ──────────────────────────────────
    data = {
        "grant_type": "authorization_code",
        "client_id": rest_key,
        "redirect_uri": REDIRECT_URI,
        "code": got["code"],
    }
    # 앱에 Client Secret이 활성화된 경우 필수 (없으면 KOE010 오류)
    secret = os.getenv("KAKAO_CLIENT_SECRET", "").strip()
    if secret:
        data["client_secret"] = secret
    resp = requests.post(TOKEN_URL, data=data, timeout=15)
    if resp.status_code != 200:
        print(f"✗ 토큰 교환 실패: {resp.status_code} {resp.text}")
        return
    tok = resp.json()
    notify._update_env("KAKAO_REFRESH_TOKEN", tok["refresh_token"])
    print("✅ 토큰 발급 성공 → .env 에 KAKAO_REFRESH_TOKEN 저장 완료")

    # ── 확인용 카톡 1건 전송 ────────────────────────────────────
    print("\n확인용 메시지를 '나와의 채팅'으로 보내봅니다...")
    ok = notify.send_text("[StockAgent] 카카오톡 알림 연동 완료! 이제 배치 리포트 요약이 자동으로 도착합니다.")
    print("✅ 전송 성공! 카톡 '나와의 채팅'을 확인하세요." if ok else "✗ 전송 실패 — 동의항목(talk_message) 설정을 확인하세요.")


if __name__ == "__main__":
    main()
