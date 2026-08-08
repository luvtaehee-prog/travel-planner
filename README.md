# 국내 여행지 추천 프로그램

날짜를 입력하면 LLM이 여행하기 좋은 국내 도시를 추천하고, 지도 API로 해당 지역 맛집을 검색한 뒤, 최종 여행 리포트를 Markdown으로 생성하는 CLI 프로그램이다.

## 1. 프로그램 개요

### 동작 흐름

```
사용자 입력 (--date)
       │
       ▼
[1/3] Gemini API (POST)  →  추천 도시 JSON 생성
       │                     { recommended_city, weather, events, reason }
       ▼
[2/3] Kakao Local API (GET)  →  recommended_city 기준 맛집 5곳 검색
       │
       ▼
[3/3] Gemini API (POST)  →  1+2 데이터를 합쳐 Markdown 리포트 생성
       │
       ▼
results/ 폴더에 원본 JSON + 리포트 저장
```

### 사용 API

| 구분 | 서비스 | 메서드 | 인증 헤더 |
|---|---|---|---|
| LLM | Google Gemini (`gemini-2.5-flash`) | POST | `x-goog-api-key` |
| 지도/장소 | Kakao Local (키워드 검색) | GET | `Authorization: KakaoAK {키}` |

### 파일 구성

```
travel_planner/
├── travel_planner.py     # 메인 프로그램
├── check_env.py          # API 키 로드 확인용 보조 스크립트
├── smoke_test.py         # 두 API 연결 확인용 보조 스크립트
├── requirements.txt      # 의존 패키지 목록
├── .env.example          # 환경변수 템플릿 (실제 키 없음)
├── .env                  # 실제 API 키 (git 제외, 제출 제외)
├── .gitignore
├── README.md
└── results/              # 실행 결과물 (자동 생성)
    ├── YYYY-MM-DD_raw.json
    └── YYYY-MM-DD_travel_plan.md
```

## 2. 개발 환경

- Python 3.10 이상 (개발 환경: Python 3.12)
- 외부 패키지: `requests`, `python-dotenv`

## 3. 설치 및 실행 방법

### 3-1. 가상환경 생성 및 패키지 설치

**macOS / Linux**
```bash
cd travel_planner
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell)**
```powershell
cd travel_planner
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3-2. API 키 설정

`.env.example`을 복사해 `.env`를 만들고 발급받은 키를 입력한다.

```bash
cp .env.example .env
```

`.env` 파일 내용:
```
GEMINI_API_KEY=발급받은_Gemini_키
KAKAO_REST_API_KEY=발급받은_카카오_REST_API_키
```

작성 규칙: `=` 앞뒤 공백 없음, 값에 따옴표 없음.

### 3-3. 실행

```bash
python travel_planner.py --date "2026-09-15"
```

가상환경 활성화가 안 될 경우 인터프리터를 직접 지정해도 된다.
```bash
./venv/bin/python travel_planner.py --date "2026-09-15"
```

### 3-4. 도움말

```bash
python travel_planner.py --help
```

## 4. API 키 발급 방법

### Google Gemini
1. https://aistudio.google.com/apikey 접속 후 구글 계정 로그인
2. **Create API key** 클릭
3. 발급된 키를 `.env`의 `GEMINI_API_KEY`에 입력

### Kakao Local
1. https://developers.kakao.com 접속 후 카카오 계정 로그인
2. **내 애플리케이션** → **애플리케이션 추가하기**
3. 생성한 앱 → **앱 키** 메뉴 → **REST API 키** 복사
   (JavaScript 키, Admin 키가 아닌 REST API 키를 사용해야 한다)
4. 좌측 메뉴에서 **카카오맵 / API 설정**의 활성화 상태를 **ON**으로 변경
   - 비활성 상태면 호출 시 `403 NotAuthorizedError / disabled OPEN_MAP_AND_LOCAL service` 오류가 발생한다
5. 발급된 키를 `.env`의 `KAKAO_REST_API_KEY`에 입력

### 연결 확인

```bash
python check_env.py    # 키가 정상적으로 로드되는지 확인
python smoke_test.py   # 두 API가 실제로 응답하는지 확인
```

## 5. 결과물 확인 방법

실행이 끝나면 `results/` 폴더에 파일 2개가 생성된다.

| 파일 | 내용 |
|---|---|
| `YYYY-MM-DD_raw.json` | 1차 추천 JSON + 맛집 검색 결과 + 오류 목록(errors) |
| `YYYY-MM-DD_travel_plan.md` | 최종 여행 리포트 |

```bash
ls results
cat results/2026-09-15_travel_plan.md
```

리포트 구성:
```
# YYYY-MM-DD 국내 여행 추천 리포트
## 추천 지역
## 추천 이유
## 날씨 요약
## 행사/축제
## 맛집 추천
## 1일 일정 제안
## 오류 요약(errors)
```

## 6. 오류 처리 정책

| 상황 | 처리 |
|---|---|
| API 키 미설정 | 즉시 종료 + 설정 방법 안내 출력 |
| 날짜 형식 오류 | 사용법 출력 후 종료 |
| 지도 API 인증 실패 (401/403) | 맛집 = "데이터 없음" 처리, 리포트 생성은 계속 진행 |
| 지도 API 쿼터 초과 (429) | 동일 |
| 지도 API 네트워크 오류 | 동일 |
| 검색 결과 0건 | 동일 |
| LLM JSON 파싱 실패 | 프롬프트를 강화해 **1회만** 재시도. 재실패 시 종료 |
| LLM 리포트 생성 실패 | 코드가 만든 기본 템플릿으로 대체 |

발생한 모든 오류는 프로그램 내부의 `ERRORS` 리스트에 누적되며, 리포트의 `## 오류 요약(errors)` 섹션과 원본 JSON의 `errors` 필드에 함께 기록된다. 오류가 없으면 빈 리스트로 남는다.

## 7. 보안 주의 사항

> **API 키를 코드, README, 결과물, 스크린샷에 절대 포함하지 않는다.**

- API 키는 소스 코드에 직접 작성하지 않고 `.env` 파일에서 읽어온다 (`python-dotenv` 사용)
- `.env` 파일은 `.gitignore`에 등록되어 있어 Git 저장소에 올라가지 않는다
- 제출 시 `.env` 파일은 제외하고 `.env.example`만 포함한다
- `check_env.py`는 키 검증 시에도 전체 값을 출력하지 않고 길이와 앞 4글자만 표시한다
- 키가 노출되었을 경우 각 콘솔에서 즉시 삭제 후 재발급한다

### `.env`를 쓰는 이유

1. **유출 방지** — 코드를 공유하거나 GitHub에 올릴 때 실수로 키가 공개되는 것을 막는다
2. **운영 편의** — 키를 교체해도 코드를 수정할 필요가 없다
3. **사고 예방** — 과금·쿼터가 걸린 서비스에서 키 유출로 인한 피해를 방지한다
## 8. 과제 목표 자기 점검

과제 문서 "3. 과제 목표"의 4개 항목에 대한 설명이다.

### 8-1. REST API의 요청/응답 구조와 GET/POST의 차이

REST API는 URL로 자원을 지정하고, HTTP 메서드로 동작을 지정한 뒤, 응답을 JSON으로 받는 구조다.

| 구분 | GET | POST |
|---|---|---|
| 용도 | 데이터 조회 | 데이터를 담아 전송 |
| 데이터 위치 | URL 쿼리스트링 (`?query=경주+맛집`) | 요청 본문(body) |
| 이 프로젝트의 사용처 | `search_restaurants()` — Kakao Local | `call_gemini()` — Gemini |

Gemini 호출에 POST를 쓴 이유는 프롬프트가 길고, URL에 노출되면 서버 로그에 남기 때문이다. Kakao 검색은 단순 조회이므로 GET을 썼다.

응답 처리는 두 API 모두 동일하다. `res.status_code`로 성공 여부를 판정하고(200 = 성공), `res.json()`으로 본문을 파이썬 dict로 변환한다.

인증 방식은 API마다 다르다.

| API | 헤더 이름 | 형식 |
|---|---|---|
| Gemini | `x-goog-api-key` | 키 값 그대로 |
| Kakao Local | `Authorization` | `KakaoAK {키}` (KakaoAK 뒤 공백 1칸 필수) |

### 8-2. LLM 출력을 JSON으로 구조화해 다음 단계 입력으로 연결하는 흐름

LLM이 자유 문장으로 답하면 프로그램이 그 안에서 도시명을 꺼낼 수 없다. 그래서 1단계에서 JSON 스키마를 강제한다.

```
[1단계] build_prompt()      : JSON 형식을 예시로 명시한 프롬프트 작성
        call_gemini()       : POST 요청
        extract_json()      : 코드블록/설명 문장 제거 후 dict 변환
        validate_schema()   : 4개 필수 키 존재 + 타입 검증
                ↓
        recommendation["recommended_city"] = "경주"
                ↓
[2단계] search_restaurants("경주")  : 이 값을 Kakao 검색어로 사용
                ↓
[3단계] build_report_prompt()       : 1+2단계 데이터를 합쳐 리포트 생성
```

`validate_schema()`가 핵심이다. JSON 파싱에 성공해도 키 이름이 다르거나(`city` vs `recommended_city`) 타입이 틀리면(`events`가 배열이 아닌 문자열) 2단계에서 엉뚱한 값이 들어간다. 문제를 발생 지점에서 즉시 잡아야 원인 추적이 가능하다.

`extract_json()`이 필요한 이유는 "JSON만 출력하라"고 지시해도 LLM이 코드블록(` ```json `)으로 감싸거나 앞뒤에 설명을 붙이는 경우가 있기 때문이다. LLM 출력은 항상 흔들림이 있다고 가정하고 방어해야 한다.

### 8-3. 외부 API 호출의 대표 오류와 대응 원칙

| 오류 유형 | 발생 조건 | 대응 | 구현 위치 |
|---|---|---|---|
| **인증** (401/403) | 키가 틀렸거나 서비스가 비활성 | 맛집을 "데이터 없음"으로 처리하고 리포트 생성은 계속 | `search_restaurants()` |
| **쿼터** (429) | 무료 사용량 한도 초과 | 동일 | `search_restaurants()` |
| **네트워크** | 인터넷 끊김, 응답 지연 | `requests.exceptions.RequestException` 캐치 + 모든 호출에 `timeout` 지정 | `search_restaurants()`, `call_gemini()` |
| **파싱** | LLM이 JSON 형식을 지키지 않음 | 프롬프트를 강화해 **1회만** 재시도. 재실패 시 종료 | `get_recommendation()` |

**대응의 3원칙**

1. **원인별로 다르게 처리한다.** 네트워크 오류는 재시도해도 같은 결과이므로 즉시 중단하지만, 파싱 오류는 프롬프트를 바꾸면 성공할 수 있으므로 재시도한다.

2. **부분 실패가 전체 실패가 되지 않게 한다.** 맛집은 리포트의 일부일 뿐이다. 맛집 검색이 실패했다고 추천 지역·날씨·일정까지 못 받는 것은 손해다. `search_restaurants()`는 어떤 실패에도 예외를 던지지 않고 빈 리스트를 반환한다.

3. **실패를 조용히 삼키지 않는다.** 빈 리스트를 반환하되 `log_error()`로 `ERRORS`에 반드시 기록한다. 기록된 오류는 리포트의 `## 오류 요약(errors)` 섹션과 원본 JSON의 `errors` 필드에 남아 사후 추적이 가능하다.

**예외 처리 (1단계만 종료하는 이유)**
1차 추천이 실패하면 도시명이 없어 2·3단계를 아예 수행할 수 없다. 3단계 리포트 생성은 실패해도 `build_fallback_report()`라는 대체 경로가 있지만, 1단계는 대체할 데이터가 없다.

**무한 재시도를 금지하는 이유**
API 과금이 계속 발생하고 프로그램이 끝나지 않을 수 있다. `get_recommendation()`의 `for attempt in range(2)`는 최초 1회 + 재시도 1회로 상한을 고정한다.

### 8-4. API 키를 코드에 쓰지 않고 `.env`/환경변수로 관리하는 이유

1. **유출 방지** — 코드를 공유하거나 GitHub에 올릴 때 키가 함께 공개되는 사고를 막는다. 이 프로젝트는 `.gitignore`에 `.env`를 등록해 실제로 차단했다.
2. **운영 편의** — 키를 교체해도 코드를 수정할 필요가 없다. 개발/운영 환경마다 다른 키를 쓸 수도 있다.
3. **사고 예방** — 과금·쿼터가 걸린 서비스에서 키가 노출되면 타인이 사용해 요금이 발생한다.

**구현**

```python
load_dotenv()                              # .env를 읽어 환경변수로 등록
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")   # 환경변수에서 읽음
```

키 문자열이 소스 코드에 전혀 등장하지 않는다.

**추가 조치**

- `check_api_keys()` — 키가 없으면 API를 호출하기 전에 종료하고 설정 방법을 안내한다. 키 없이 호출해 나오는 401 메시지만으로는 원인 파악이 어렵기 때문이다.
- `check_env.py` — 키 검증 시에도 전체 값을 출력하지 않고 길이와 앞 4글자만 표시한다. 화면 캡처나 로그에 키가 남지 않게 하기 위해서다.
- `.env.example` — 실제 값 없이 키 이름만 담은 템플릿. `.env`가 저장소에서 제외되므로, 이 파일이 없으면 다른 사람이 어떤 키가 필요한지 알 수 없다.