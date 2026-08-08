import os
import requests
from dotenv import load_dotenv

load_dotenv()

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
KAKAO_KEY = os.getenv("KAKAO_REST_API_KEY")


def test_gemini():
    print("\n[1] Gemini 연결 확인")
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    headers = {"x-goog-api-key": GEMINI_KEY}
    try:
        res = requests.get(url, headers=headers, timeout=15)
        print(f"    HTTP {res.status_code}")
        if res.status_code != 200:
            print(f"    실패 본문: {res.text[:300]}")
            return
        models = res.json().get("models", [])
        usable = [
            m["name"].replace("models/", "")
            for m in models
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
        print(f"    사용 가능 모델 {len(usable)}개")
        for name in usable:
            if "flash" in name:
                print(f"      - {name}")
    except Exception as e:
        print(f"    예외: {type(e).__name__}: {e}")


def test_kakao():
    print("\n[2] Kakao Local 연결 확인")
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_KEY}"}
    params = {"query": "제주 맛집", "size": 3}
    try:
        res = requests.get(url, headers=headers, params=params, timeout=15)
        print(f"    HTTP {res.status_code}")
        if res.status_code != 200:
            print(f"    실패 본문: {res.text[:300]}")
            return
        docs = res.json().get("documents", [])
        print(f"    검색 결과 {len(docs)}건")
        for d in docs:
            print(f"      - {d['place_name']} / {d['address_name']}")
    except Exception as e:
        print(f"    예외: {type(e).__name__}: {e}")


test_gemini()
test_kakao()