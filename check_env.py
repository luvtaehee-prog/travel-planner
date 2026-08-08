import os
from dotenv import load_dotenv

load_dotenv()

for name in ["GEMINI_API_KEY", "KAKAO_REST_API_KEY"]:
    value = os.getenv(name)
    if not value:
        print(f"[FAIL] {name}: 설정되지 않음")
    else:
        print(f"[OK]   {name}: 길이 {len(value)}, 앞 4글자 {value[:4]}****")
        