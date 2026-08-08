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