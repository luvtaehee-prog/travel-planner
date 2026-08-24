"""
국내 여행지 추천 프로그램
=========================
[프로그램 흐름]
  1단계: Gemini API(LLM)가 날짜를 받아 추천 도시를 JSON으로 생성
  2단계: 1단계 JSON의 도시명을 Kakao Local API(지도)에 넘겨 맛집 검색
  3단계: 1+2단계 데이터를 다시 Gemini에 넘겨 Markdown 리포트 생성
  4단계: results/ 폴더에 원본 JSON과 리포트를 저장

[핵심 설계 원칙]
  - LLM 출력을 JSON으로 구조화해야 다음 단계(지도 API)의 입력으로 쓸 수 있다.
  - 지도 API가 실패해도 프로그램은 멈추지 않는다(맛집=데이터 없음으로 계속 진행).
  - API 키는 코드에 쓰지 않고 .env 파일에서 읽는다.
"""

# ── 표준 라이브러리 (파이썬에 기본 포함, 설치 불필요) ─────────────────
import argparse  # CLI 명령줄 옵션(--date)을 파싱
import json      # JSON 문자열 <-> 파이썬 dict 상호 변환
import os        # 환경변수 읽기, 폴더 생성, 경로 조합
import sys       # sys.exit()로 프로그램 강제 종료
from datetime import datetime  # 날짜 형식 검증, 생성 시각 기록

# ── 외부 라이브러리 (pip install 필요) ────────────────────────────────
import requests               # HTTP 요청(GET/POST)을 보내는 라이브러리
from dotenv import load_dotenv  # .env 파일을 읽어 환경변수로 등록


# ══════════════════════════════════════════════════════════════════
# 설정값 (상수)
# ══════════════════════════════════════════════════════════════════

# .env 파일을 읽어 그 안의 KEY=VALUE 를 환경변수로 등록한다.
# 이 줄이 os.getenv()보다 먼저 실행되어야 키를 읽을 수 있다.
load_dotenv()

# os.getenv()는 환경변수를 읽는다. 키가 없으면 None을 반환한다.
# [보안 핵심] 키 문자열이 코드에 전혀 등장하지 않는다.
#   → GitHub에 코드를 올려도 키가 유출되지 않는다.
#   → 키를 교체해도 .env만 바꾸면 되고 코드 수정이 불필요하다.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")

# 사용할 Gemini 모델명. 상수로 빼두면 모델 교체 시 이 줄만 고치면 된다.
GEMINI_MODEL = "gemini-3.6-flash"

# Gemini의 텍스트 생성 엔드포인트 URL.
# :generateContent 는 "이 모델로 콘텐츠를 생성하라"는 동작을 지정한다.
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/"
    f"models/{GEMINI_MODEL}:generateContent"
)

# Kakao Local의 키워드 검색 엔드포인트 URL.
KAKAO_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"

# 결과물을 저장할 폴더명.
RESULTS_DIR = "results"

# 1차 추천 JSON에 반드시 있어야 하는 키 목록 (과제 명세의 최소 스키마).
REQUIRED_KEYS = ["recommended_city", "weather", "events", "reason"]

# 실행 중 발생한 모든 오류를 누적하는 리스트.
# [설계 의도] 오류가 나도 프로그램을 죽이지 않고 여기에 쌓아둔 뒤,
#            마지막에 리포트의 errors 섹션과 원본 JSON에 함께 기록한다.
#            → "어디서 무엇이 실패했는지" 추적 가능한 상태를 유지한다.
ERRORS = []


def log_error(step, err_type, message):
    """
    오류 하나를 ERRORS 리스트에 기록한다.

    Args:
        step:     어느 단계에서 났는지 (llm_recommend / place_search / llm_report)
        err_type: 오류 종류 (AUTH_ERROR / EMPTY_RESULT / PARSE_ERROR 등)
        message:  상세 메시지

    str(message)로 감싸는 이유:
        예외 객체(Exception)는 JSON으로 저장할 수 없다. 문자열로 변환해야
        나중에 json.dump()에서 오류가 나지 않는다.
    """
    ERRORS.append({"step": step, "type": err_type, "message": str(message)})


# ══════════════════════════════════════════════════════════════════
# [영역 1] CLI 인터페이스 — 사용자 입력 처리
# ══════════════════════════════════════════════════════════════════


def parse_args():
    """
    CLI 옵션을 정의하고 사용자가 입력한 값을 파싱한다.

    argparse를 쓰는 이유:
        - --help 를 자동으로 만들어 준다.
        - required=True 인 옵션이 빠지면 자동으로 사용법을 출력하고 종료한다.
        - 직접 sys.argv를 파싱하는 것보다 훨씬 적은 코드로 안전하게 처리된다.

    Returns:
        (파싱된 인자 객체, parser 객체)
        parser도 함께 반환하는 이유: 날짜 형식이 틀렸을 때
        parser.print_help()로 사용법을 다시 보여주기 위해서다.
    """
    parser = argparse.ArgumentParser(
        description="입력한 날짜에 맞는 국내 여행지를 추천하고 리포트를 생성한다."
    )
    parser.add_argument(
        "--date",
        required=True,  # 이 옵션이 없으면 argparse가 알아서 오류 + 종료
        help='여행 날짜. 형식: YYYY-MM-DD (예: --date "2026-09-15")',
    )
    return parser.parse_args(), parser


def validate_date(date_str, parser):
    """
    날짜 문자열이 YYYY-MM-DD 형식인지 검증한다.

    검증 방법:
        datetime.strptime(문자열, 형식)은 문자열을 날짜로 변환한다.
        형식이 맞지 않으면 ValueError 예외를 던진다.
        이 성질을 이용해 "예외가 안 나면 올바른 형식"으로 판정한다.

    이 방식의 장점:
        정규표현식으로 검사하면 "2026-13-45" 같은 값이 통과한다.
        strptime은 실제 달력상 존재하는 날짜인지까지 검사한다.

    실패 시 동작:
        오류 메시지 + 사용법 출력 후 종료 코드 1로 종료한다.
        (종료 코드 0 = 정상, 1 이상 = 오류. 셸 스크립트 관례)
    """
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        print(f"[오류] 날짜 형식이 올바르지 않습니다: {date_str}")
        print('올바른 형식: YYYY-MM-DD (예: "2026-09-15")\n')
        parser.print_help()
        sys.exit(1)
    return date_str


def check_api_keys():
    """
    두 API 키가 모두 설정되어 있는지 확인한다.

    [과제 요구사항] "API 키 미설정: 즉시 종료 + 설정 방법 안내 출력"

    이 검사를 API 호출 전에 하는 이유:
        키 없이 호출하면 401 오류가 나는데, 그 메시지만 봐서는
        초보자가 원인을 알기 어렵다. 미리 잡아서 해결 방법까지 알려준다.

    missing 리스트를 쓰는 이유:
        키가 2개 다 없을 때 두 개를 한 번에 알려주기 위해서다.
        하나씩 검사하고 즉시 종료하면 사용자가 두 번 실행해야 한다.
    """
    missing = []
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if not KAKAO_REST_API_KEY:
        missing.append("KAKAO_REST_API_KEY")

    if missing:
        print("[오류] 다음 API 키가 설정되지 않았습니다:")
        for name in missing:
            print(f"  - {name}")
        print("\n[설정 방법]")
        print("  1) 프로젝트 폴더에 .env 파일을 만든다.")
        print("  2) 아래 형식으로 키를 입력한다 (따옴표/공백 없이).")
        print("       GEMINI_API_KEY=발급받은_키")
        print("       KAKAO_REST_API_KEY=발급받은_키")
        print("  3) .env 파일은 절대 공유하거나 제출물에 포함하지 않는다.")
        sys.exit(1)


# ══════════════════════════════════════════════════════════════════
# [영역 2] Gemini API — LLM 호출과 JSON 구조화
# ══════════════════════════════════════════════════════════════════


def call_gemini(prompt):
    """
    Gemini API에 프롬프트를 보내고 생성된 텍스트를 반환한다.

    [POST를 쓰는 이유]
        GET은 데이터를 URL 뒤(?query=...)에 붙여 보낸다. 길이 제한이 있고
        URL이 로그에 남는다. 프롬프트는 길고 내용이 중요하므로
        요청 본문(body)에 담아 보내는 POST를 쓴다.
        → 조회는 GET, 데이터를 담아 보내면 POST 라고 이해하면 된다.

    [헤더(headers)]
        x-goog-api-key : Gemini가 요구하는 인증 헤더 이름
        Content-Type   : 본문이 JSON 형식임을 서버에 알림

    [본문(payload)]
        Gemini가 요구하는 고정 구조:
        {"contents": [{"parts": [{"text": "프롬프트"}]}]}
        중첩이 깊은 이유는 여러 턴의 대화, 이미지 등을 함께
        담을 수 있도록 설계되었기 때문이다.

    [json=payload]
        requests가 dict를 자동으로 JSON 문자열로 변환해 준다.
        data=json.dumps(payload) 를 직접 쓰는 것과 같은 효과다.

    [timeout=60]
        서버가 응답하지 않을 때 무한 대기하는 것을 막는다.
        LLM 생성은 오래 걸릴 수 있어 60초로 넉넉히 준다.
    """
    headers = {
        "x-goog-api-key": GEMINI_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    res = requests.post(GEMINI_URL, headers=headers, json=payload, timeout=60)

    # HTTP 상태 코드 200 = 성공. 그 외는 실패로 간주하고 예외를 던진다.
    # res.text[:200] : 오류 본문이 매우 길 수 있어 앞 200자만 잘라 보여준다.
    if res.status_code != 200:
        raise RuntimeError(f"HTTP {res.status_code}: {res.text[:200]}")

    # res.json() : 응답 본문(JSON 문자열)을 파이썬 dict로 변환한다.
    data = res.json()

    # Gemini 응답 구조에서 실제 생성 텍스트가 있는 위치:
    #   candidates(후보 답변 목록)[0] → content → parts[0] → text
    return data["candidates"][0]["content"]["parts"][0]["text"]


def extract_json(text):
    """
    LLM 응답 텍스트에서 JSON 부분만 잘라내어 dict로 변환한다.

    [이 함수가 필요한 이유]
        프롬프트로 "JSON만 출력하라"고 지시해도 LLM은 종종
```json
          {...}
```
        처럼 코드블록으로 감싸거나, 앞뒤에 "알겠습니다" 같은 말을 붙인다.
        그 상태로 json.loads()를 부르면 파싱 오류가 난다.
        LLM 출력은 항상 이런 흔들림이 있다고 가정하고 방어해야 한다.

    [처리 순서]
        1) ``` 로 시작하면 코드블록 마커를 제거
        2) 첫 번째 { 와 마지막 } 사이만 잘라낸다
           → 앞뒤에 붙은 설명 문장이 자동으로 제거된다
        3) json.loads()로 dict 변환
    """
    cleaned = text.strip()  # 앞뒤 공백/개행 제거

    # 1) 코드블록 마커 제거
    if cleaned.startswith("```"):
        # "```json\n{...}\n```" 을 ``` 로 나누면 [ "", "json\n{...}\n", "" ]
        # 가운데(인덱스 1)가 실제 내용이다.
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]  # "json" 4글자 제거

    # 2) 중괄호 범위만 추출
    start = cleaned.find("{")   # 첫 { 위치. 없으면 -1
    end = cleaned.rfind("}")    # 마지막 } 위치(rfind는 뒤에서부터 탐색). 없으면 -1
    if start == -1 or end == -1:
        raise ValueError("응답에서 JSON 객체를 찾을 수 없음")

    # 3) 문자열 → dict 변환. end+1 인 이유는 슬라이싱이 끝 인덱스를 제외하기 때문
    return json.loads(cleaned[start : end + 1])


def validate_schema(data):
    """
    파싱된 dict가 과제에서 요구한 스키마를 만족하는지 검사한다.

    [이 검사가 필요한 이유]
        JSON 파싱에 성공했다고 해서 내용이 맞다는 보장은 없다.
        예를 들어 LLM이 recommended_city 대신 city 라는 키를 쓰거나,
        events를 배열이 아닌 문자열로 줄 수 있다.
        그대로 두면 다음 단계(Kakao 검색)에서 엉뚱한 값이 들어가
        원인을 찾기 어려운 오류가 난다.
        → 문제를 "발생한 지점"에서 즉시 잡는 것이 디버깅 비용을 줄인다.

    isinstance(값, 타입) : 값이 해당 타입인지 확인하는 내장 함수
    """
    # (1) 필수 키가 모두 존재하는지
    for key in REQUIRED_KEYS:
        if key not in data:
            raise ValueError(f"필수 키 누락: {key}")

    # (2) 각 값의 타입이 맞는지
    if not isinstance(data["recommended_city"], str):
        raise ValueError("recommended_city는 문자열이어야 함")
    if not isinstance(data["weather"], str):
        raise ValueError("weather는 문자열이어야 함")
    if not isinstance(data["events"], list):
        raise ValueError("events는 배열이어야 함")
    if not isinstance(data["reason"], str):
        raise ValueError("reason은 문자열이어야 함")

    return data


def build_prompt(date, retry=False):
    """
    1차 추천용 프롬프트를 만든다.

    [프롬프트 설계 포인트]
        1) 역할 부여("너는 ~ 전문가다")로 응답의 일관성을 높인다.
        2) 원하는 JSON 형태를 예시로 직접 보여준다(가장 효과적).
        3) "설명, 인사말, 마크다운 코드블록을 붙이지 마라"처럼
           하지 말아야 할 것을 명시한다.

    [f-string 안의 중괄호]
        f"..." 안에서 { } 는 변수 자리로 해석된다.
        JSON 예시의 중괄호를 그대로 출력하려면 {{ }} 로 두 번 써야 한다.

    Args:
        retry: 재시도 여부. True면 파싱 실패 사실을 알리는 문장을 덧붙여
               모델이 더 엄격하게 JSON만 출력하도록 유도한다.
               (과제 요구: "필수 키만 다시 JSON으로 출력하도록 프롬프트를 수정해 재시도")
    """
    base = f"""너는 한국 국내 여행 추천 전문가다.
{date}에 여행하기 좋은 국내 도시 1곳을 추천하라.

아래 JSON 형식으로만 응답하라. 설명, 인사말, 마크다운 코드블록을 절대 붙이지 마라.

{{
  "recommended_city": "도시명 (예: 제주, 강릉)",
  "weather": "해당 시기의 일반적인 날씨 요약 1~2문장",
  "events": ["행사 또는 축제 후보", "최대 3개"],
  "reason": "추천 근거 2~4문장"
}}"""

    if retry:
        base += "\n\n중요: 직전 응답이 JSON 파싱에 실패했다. 위 4개 키만 담긴 순수 JSON 객체 하나만 출력하라."

    return base


def get_recommendation(date):
    """
    1차 추천 JSON을 얻는다. 파싱에 실패하면 딱 1회만 재시도한다.

    [range(2)의 의미]
        attempt = 0 → 최초 시도
        attempt = 1 → 재시도 (is_retry = True)
        총 2회 = 최초 1회 + 재시도 1회
        [과제 제약] "재시도는 최대 1회만 허용한다(무한 재시도 금지)"
        무한 재시도를 금지하는 이유: API 과금이 계속 발생하고,
        프로그램이 영원히 끝나지 않을 수 있기 때문이다.

    [예외를 종류별로 나눠 잡는 이유]
        - ValueError / JSONDecodeError : LLM 출력 형식 문제 → 재시도할 가치가 있음
        - RequestException(네트워크)     : 재시도해도 같은 결과 → 즉시 중단
        - RuntimeError(HTTP 오류)        : 키/쿼터 문제 → 즉시 중단
        원인에 따라 대응을 다르게 하는 것이 오류 처리의 핵심이다.
    """
    for attempt in range(2):
        is_retry = attempt == 1
        try:
            text = call_gemini(build_prompt(date, retry=is_retry))
            data = extract_json(text)
            return validate_schema(data)  # 성공하면 여기서 함수가 끝난다

        except (ValueError, json.JSONDecodeError) as e:
            # 파싱/스키마 실패 → 기록하고 반복문의 다음 회차로 넘어간다
            print(f"    - JSON 파싱 실패 ({attempt + 1}회차): {e}")
            log_error("llm_recommend", "PARSE_ERROR", e)
            if is_retry:  # 재시도까지 실패했으면 포기
                raise RuntimeError("JSON 파싱 재시도 실패")

        except requests.exceptions.RequestException as e:
            # 네트워크 끊김, 타임아웃 등
            log_error("llm_recommend", "NETWORK_ERROR", e)
            raise RuntimeError(f"네트워크 오류: {e}")

        except RuntimeError as e:
            # call_gemini가 던진 HTTP 오류 (401 인증, 429 쿼터 등)
            log_error("llm_recommend", "API_ERROR", e)
            raise


# ══════════════════════════════════════════════════════════════════
# [영역 3] Kakao Local API — 맛집 검색
# ══════════════════════════════════════════════════════════════════


def search_restaurants(city, size=5):
    """
    Kakao Local API로 맛집을 검색한다.

    [이 함수의 가장 중요한 설계 원칙]
        어떤 실패가 나도 예외를 밖으로 던지지 않고 빈 리스트 []를 반환한다.
        [과제 요구] "지도/장소 API 실패 시에도 리포트 생성은 계속 진행"
        → 맛집은 리포트의 일부일 뿐이므로, 맛집 하나 때문에
          추천 지역/날씨/일정까지 전부 못 받는 상황을 막는다.
        → 대신 log_error()로 실패 사실은 반드시 남긴다.
          (조용히 실패를 삼키면 나중에 원인을 찾을 수 없다)

    [GET을 쓰는 이유]
        데이터를 "조회"하는 요청이므로 GET.
        검색어는 params에 담아 URL 뒤에 ?query=경주+맛집&size=5 로 붙는다.

    [인증 헤더]
        Authorization: KakaoAK {키}
        "KakaoAK" 뒤 공백 1칸이 반드시 필요하다. 빠지면 401이 난다.
        Gemini(x-goog-api-key)와 헤더 이름·형식이 다르다는 점에 주의.
        → API마다 인증 방식이 다르므로 항상 공식 문서를 확인해야 한다.

    [category_group_code="FD6"]
        FD6 = 음식점 카테고리 코드. 카페만 원하면 CE7.
        키워드에만 의존하지 않고 카테고리로 한 번 더 걸러 정확도를 높인다.
    """
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}
    params = {
        "query": f"{city} 맛집",
        "size": size,
        "category_group_code": "FD6",
    }

    # ── 오류 케이스 1: 네트워크 실패 (인터넷 끊김, 타임아웃) ──────────
    try:
        res = requests.get(KAKAO_URL, headers=headers, params=params, timeout=15)
    except requests.exceptions.RequestException as e:
        print(f"    - 오류: 네트워크 실패. {e}")
        log_error("place_search", "NETWORK_ERROR", e)
        return []

    # ── 오류 케이스 2: 인증 실패 ──────────────────────────────────
    # 401 = 키가 잘못됨 / 403 = 키는 맞지만 권한이 없음
    #        (예: 카카오 콘솔에서 지도 서비스가 비활성 상태)
    if res.status_code in (401, 403):
        print(f"    - 오류: 인증 실패({res.status_code}). 키 설정을 확인하세요.")
        print("    - 맛집 섹션은 '데이터 없음'으로 처리하고 계속 진행합니다.")
        log_error("place_search", "AUTH_ERROR", f"HTTP {res.status_code}")
        return []

    # ── 오류 케이스 3: 쿼터 초과 ──────────────────────────────────
    # 429 = Too Many Requests. 무료 사용량 한도를 넘겼을 때 발생
    if res.status_code == 429:
        print("    - 오류: 요청 한도 초과(429).")
        log_error("place_search", "QUOTA_ERROR", "HTTP 429")
        return []

    # ── 오류 케이스 4: 기타 HTTP 오류 (500 서버 오류 등) ────────────
    if res.status_code != 200:
        print(f"    - 오류: HTTP {res.status_code}")
        log_error("place_search", "HTTP_ERROR", f"HTTP {res.status_code}")
        return []

    # ── 오류 케이스 5: 응답이 JSON이 아님 ──────────────────────────
    # .get("documents", []) : 키가 없어도 KeyError 대신 빈 리스트를 준다
    try:
        documents = res.json().get("documents", [])
    except ValueError as e:
        print(f"    - 오류: 응답 파싱 실패. {e}")
        log_error("place_search", "PARSE_ERROR", e)
        return []

    # ── 오류 케이스 6: 호출은 성공했지만 검색 결과가 0건 ────────────
    # [과제 요구] "검색 결과가 0건이면 프로그램이 중단되지 않아야 하며,
    #             '데이터 없음' 상태로 다음 단계로 진행한다"
    if not documents:
        print("    - 검색 결과 0건")
        log_error("place_search", "EMPTY_RESULT", f"0 results for query={city} 맛집")
        return []

    # ── 정상 처리: 필요한 필드만 뽑아 재구성 ───────────────────────
    # [왜 그대로 쓰지 않고 다시 만드는가]
    #   카카오 응답에는 안 쓰는 필드가 많고 이름도 카카오 방식이다.
    #   내 프로그램이 쓸 형태로 한 번 정리해두면,
    #   나중에 네이버 API로 바꿔도 이 dict 구조는 그대로 유지된다.
    #   → 뒷단(리포트 생성)을 고칠 필요가 없다.
    restaurants = []
    for doc in documents:
        restaurants.append(
            {
                "name": doc.get("place_name", ""),
                # 도로명 주소를 우선 쓰되, 없으면(빈 문자열이면) 지번 주소를 쓴다.
                # 파이썬의 or 는 앞 값이 비어 있을 때 뒤 값을 준다.
                "address": doc.get("road_address_name") or doc.get("address_name", ""),
                "category": doc.get("category_name", ""),
                "phone": doc.get("phone", ""),
                "url": doc.get("place_url", ""),
                # 카카오는 좌표를 문자열로 준다. 숫자로 변환해 저장한다.
                # x=경도(longitude), y=위도(latitude)
                "x": float(doc["x"]) if doc.get("x") else None,
                "y": float(doc["y"]) if doc.get("y") else None,
            }
        )

    print(f"    - 맛집 {len(restaurants)}곳 검색 완료")
    return restaurants


# ══════════════════════════════════════════════════════════════════
# [영역 4] 최종 리포트 생성
# ══════════════════════════════════════════════════════════════════


def build_report_prompt(date, recommendation, restaurants):
    """
    최종 리포트용 프롬프트를 만든다.

    [이 단계가 이 과제의 핵심]
        LLM(1단계) → 지도 API(2단계) → LLM(3단계)
        서로 다른 두 API의 데이터를 하나로 합쳐 최종 결과를 만든다.
        단일 API 호출이 아니라 "여러 API를 엮어 인사이트를 만드는" 흐름이다.

    [환각(hallucination) 방지]
        "위 검색 결과만 사용하라. 없는 가게를 지어내지 마라"
        이 지시가 없으면 LLM은 그럴듯한 가짜 식당 이름을 만들어낸다.
        실제 데이터를 넣었어도 명시적으로 제한해야 한다.
    """
    # 맛집이 있으면 목록 문자열로, 없으면 "데이터 없음"으로 만든다.
    if restaurants:
        lines = []
        for r in restaurants:
            lines.append(
                f"- {r['name']} | {r['address']} | {r['category']} | {r['url']}"
            )
        restaurant_block = "\n".join(lines)  # 리스트를 개행으로 이어붙임
    else:
        restaurant_block = "데이터 없음 (장소 검색 결과 0건 또는 API 실패)"

    return f"""너는 여행 리포트 작성자다.
아래 데이터를 바탕으로 Markdown 형식의 여행 리포트를 작성하라.

[여행 날짜]
{date}

[1차 추천 데이터]
추천 도시: {recommendation['recommended_city']}
날씨 요약: {recommendation['weather']}
행사/축제: {', '.join(recommendation['events']) if recommendation['events'] else '없음'}
추천 이유: {recommendation['reason']}

[맛집 검색 결과]
{restaurant_block}

[작성 규칙]
1. 아래 순서와 제목을 그대로 사용하라.
   # {date} 국내 여행 추천 리포트
   ## 추천 지역
   ## 추천 이유
   ## 날씨 요약
   ## 행사/축제
   ## 맛집 추천
   ## 1일 일정 제안
2. 맛집 추천 섹션에는 위 검색 결과만 사용하라. 없는 가게를 지어내지 마라.
3. 맛집 데이터가 "데이터 없음"이면 그대로 "- 데이터 없음 (장소 검색 결과 0건)"이라고 쓰라.
4. 1일 일정 제안은 오전 / 오후 / 저녁 3개 항목으로 작성하라.
5. Markdown 본문만 출력하라. 코드블록으로 감싸지 마라."""


def generate_report(date, recommendation, restaurants):
    """
    LLM으로 최종 리포트 Markdown을 생성한다.

    [실패 대비]
        3번째 API 호출까지 와서 실패하면, 앞의 두 단계에서 얻은
        데이터가 전부 버려진다. 그건 낭비다.
        → 실패하면 build_fallback_report()로 코드가 직접 리포트를 만든다.
          품질은 떨어지지만 결과물은 반드시 남는다.

    [except Exception 을 쓴 이유]
        이 지점은 "무슨 오류든 프로그램을 죽여선 안 되는" 위치다.
        다만 넓게 잡는 만큼 log_error로 원인을 반드시 기록한다.
    """
    try:
        text = call_gemini(build_report_prompt(date, recommendation, restaurants))

        # 리포트도 코드블록으로 감싸져 올 수 있으므로 제거한다.
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("markdown"):
                cleaned = cleaned[8:]  # "markdown" 8글자 제거
        return cleaned.strip()

    except Exception as e:
        print(f"    - 오류: 리포트 생성 실패. 기본 템플릿으로 대체합니다. {e}")
        log_error("llm_report", "API_ERROR", e)
        return build_fallback_report(date, recommendation, restaurants)


def build_fallback_report(date, recommendation, restaurants):
    """
    LLM 리포트 생성이 실패했을 때 코드가 직접 만드는 기본 Markdown.

    [구현 방식]
        문자열을 += 로 계속 이어붙이면 매번 새 문자열이 생성되어 비효율적이다.
        리스트에 줄 단위로 담았다가 마지막에 "\n".join() 으로 합치는 것이
        파이썬에서 권장되는 방식이다.
    """
    lines = [
        f"# {date} 국내 여행 추천 리포트",
        "",
        "## 추천 지역",
        f"- {recommendation['recommended_city']}",
        "",
        "## 추천 이유",
        recommendation["reason"],
        "",
        "## 날씨 요약",
        recommendation["weather"],
        "",
        "## 행사/축제",
    ]

    if recommendation["events"]:
        for event in recommendation["events"]:
            lines.append(f"- {event}")
    else:
        lines.append("- 데이터 없음")

    lines += ["", "## 맛집 추천"]

    if restaurants:
        for r in restaurants:
            lines.append(f"- **{r['name']}** ({r['category']})")
            lines.append(f"  - 주소: {r['address']}")
            if r["url"]:
                lines.append(f"  - 링크: {r['url']}")
    else:
        lines.append("- 데이터 없음 (장소 검색 결과 0건)")

    lines += [
        "",
        "## 1일 일정 제안",
        "- 오전: 주요 명소 방문",
        "- 오후: 맛집에서 점심 후 시내 산책",
        "- 저녁: 야경 명소 방문",
    ]

    return "\n".join(lines)


def append_errors_section(report_md):
    """
    리포트 맨 끝에 오류 요약 섹션을 붙인다.

    [왜 LLM에게 맡기지 않고 코드가 직접 붙이는가]
        오류 기록은 정확해야 한다. LLM에게 맡기면 내용을 요약하거나
        빠뜨릴 수 있다. ERRORS 리스트를 코드가 그대로 옮겨 적으면
        100% 정확하다.
        → 규칙이 명확한 부분은 코드로, 자연어 생성이 필요한 부분만
          LLM에 맡기는 것이 역할 분담의 원칙이다.

    [과제 요구] "실패가 발생하면 결과 리포트에 errors 섹션으로 요약을 남긴다
                (빈 리스트여도 무방)"
    """
    lines = [report_md.rstrip(), "", "## 오류 요약(errors)"]

    if ERRORS:
        for e in ERRORS:
            lines.append(f"- `{e['step']}` / `{e['type']}` : {e['message']}")
    else:
        lines.append("- 없음")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# [영역 5] 결과 저장
# ══════════════════════════════════════════════════════════════════


def save_results(date, recommendation, restaurants, report_md):
    """
    results/ 폴더에 원본 JSON과 최종 리포트를 저장한다.

    [원본 JSON을 따로 남기는 이유]
        리포트(.md)는 사람이 읽는 최종 결과물이라 가공되어 있다.
        API가 실제로 뭘 돌려줬는지 확인하거나, 나중에 다른 형식으로
        다시 만들려면 가공 전 원본이 필요하다.
        → 원본 보존과 결과 가공을 분리하는 것이 데이터 처리의 기본이다.

    [os.path.join() 을 쓰는 이유]
        경로를 "results/" + 파일명 으로 직접 이어붙이면
        운영체제마다 구분자가 달라(맥/리눅스 '/', 윈도우 '\\') 문제가 생긴다.
        os.path.join()이 알아서 맞춰준다.
    """
    # 폴더가 없으면 만든다. 이미 있으면 아무 일도 하지 않는다.
    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)

    # 원본 데이터 구조. [과제 요구] 1차 추천 + 맛집 결과 + errors 포함
    raw = {
        "date": date,
        # 언제 생성됐는지 기록. timespec="seconds"로 마이크로초를 잘라 읽기 쉽게 함
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "recommendation": recommendation,
        "restaurants": restaurants,
        "errors": ERRORS,
    }

    # 파일명에 날짜를 넣어 실행할 때마다 구분되게 한다.
    json_path = os.path.join(RESULTS_DIR, f"{date}_raw.json")
    md_path = os.path.join(RESULTS_DIR, f"{date}_travel_plan.md")

    # with open(...) 을 쓰면 블록이 끝날 때 파일이 자동으로 닫힌다.
    # "w" = 쓰기 모드(기존 내용 덮어씀)
    # encoding="utf-8" = 한글 깨짐 방지. 생략하면 윈도우에서 깨진다.
    with open(json_path, "w", encoding="utf-8") as f:
        # ensure_ascii=False : 한글을 \uc81c\uc8fc 대신 "제주"로 저장
        # indent=2           : 들여쓰기해서 사람이 읽을 수 있게 저장
        json.dump(raw, f, ensure_ascii=False, indent=2)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    return json_path, md_path


# ══════════════════════════════════════════════════════════════════
# [영역 6] 메인 실행 흐름
# ══════════════════════════════════════════════════════════════════


def main():
    """
    프로그램 전체 흐름을 순서대로 실행한다.

    [main을 별도 함수로 두는 이유]
        전체 흐름이 이 함수 하나만 봐도 파악된다.
        세부 구현은 각 함수 안에 있고, main은 순서만 보여준다.
    """
    # ── 준비: 입력 검증 ───────────────────────────────────────────
    args, parser = parse_args()
    date = validate_date(args.date, parser)
    check_api_keys()

    # ── [1/3] LLM으로 추천 도시 결정 ─────────────────────────────
    print("[1/3] 1차 추천 생성 중(LLM)...")
    try:
        recommendation = get_recommendation(date)
    except RuntimeError as e:
        # 1단계가 실패하면 도시명이 없어 2·3단계를 할 수 없다.
        # 이 단계만은 예외적으로 프로그램을 종료한다.
        print(f"[치명적 오류] 1차 추천 실패: {e}")
        sys.exit(1)

    city = recommendation["recommended_city"]
    print(f'    - recommended_city: "{city}"')

    # ── [2/3] 1단계 결과를 입력으로 지도 API 호출 ────────────────
    # 여기가 "LLM 출력을 구조화해서 다음 단계 입력으로 연결"하는 지점이다.
    # recommended_city 라는 키로 값을 꺼내 쓸 수 있는 것은
    # 1단계에서 JSON 스키마를 강제했기 때문이다.
    print("[2/3] 맛집 검색 중(지도/장소 API)...")
    restaurants = search_restaurants(city)

    # ── [3/3] 두 API 데이터를 합쳐 최종 리포트 생성 ──────────────
    print("[3/3] 최종 리포트 생성 중(LLM)...")
    report_md = generate_report(date, recommendation, restaurants)
    report_md = append_errors_section(report_md)
    print("    - 리포트 생성 완료")

    # ── 저장 및 안내 ────────────────────────────────────────────
    json_path, md_path = save_results(date, recommendation, restaurants, report_md)

    print(f"\n완료! {md_path} 를 확인하세요.")
    print(f"      원본 데이터: {json_path}")
    if ERRORS:
        print(f"      오류 {len(ERRORS)}건이 리포트의 errors 섹션에 기록되었습니다.")


# 이 파일을 직접 실행할 때만 main()을 호출한다.
# 다른 파일이 import travel_planner 로 불러올 때는 실행되지 않는다.
# (__name__ 은 직접 실행 시 "__main__", import 시에는 모듈명이 들어간다)
if __name__ == "__main__":
    main()