# 부산 상권 변화지표 데이터 수집 프로젝트 — 개발 지침

## 1. 프로젝트 목적

부산광역시의 상권 변화 데이터를 공식 공공데이터 API로 수집하고, 분석 가능한 CSV 데이터셋으로 정리한다. 향후 **상권 단위 금융지원 우선순위 제안** 프로젝트의 탐색적 데이터 분석(EDA)에 활용한다.

- **핵심 의사결정 질문:** 어느 상권에 점검·컨설팅·특례보증 등 지원 자원을 먼저 배치할 것인가?
- **예상 사용자:** 부산 구·군청 상권 담당자 및 지역신용보증기관의 자원 배분 담당자
- **현재 범위:** API 접근 확인 → 원본 수집 → 데이터 검증 → CSV 저장 → 기초 EDA
- **범위 밖:** 근거 없는 위험점수 산정, 금융지원 효과의 인과관계 주장, 실제 금융지원 승인 자동화

## 2. 데이터 출처 및 확인된 API 명세

- 데이터명: **부산광역시_상권 변화지표정보서비스**
- 출처: 공공데이터포털 (https://www.data.go.kr/data/15095252/openapi.do)
- API 문서상 서비스: `BusanCommercialChangeService`
- 엔드포인트: `http://apis.data.go.kr/6260000/BusanCommercialChangeService/getCommercialChangeList`
- 방식: REST `GET`
- 인증: 공공데이터포털에서 발급받은 `serviceKey`
- 응답: XML 또는 JSON (`resultType=json` 사용 시 JSON 요청)
- 주요 요청 파라미터: `serviceKey`, `numOfRows`, `pageNo`, `resultType`(선택)
- 문서상 갱신주기: **1년**
- 문서 예시의 `totalCount`는 447건과 477건으로 서로 다르게 표기되어 있음. **현재 건수는 실제 API 응답을 기준으로 확인할 것.**

### 주요 응답 필드

| 필드 | 의미 |
|---|---|
| `type_nm` | 상권구분명 |
| `comm_nm` | 상권명 |
| `change_indicator_nm` | 상권 변화지표값(예: 상권확장, 상권축소, 정체, 다이나믹) |
| `average_open_months` | 평균 생존 개월 수 |
| `average_close_months` | 평균 폐업 개월 수 |
| `busan_average_open_months` | 부산 평균 생존 개월 수 |
| `busan_average_close_months` | 부산 평균 폐업 개월 수 |

**주의:** 이 API 문서에는 월별 관측일자, 구·군 코드, 주소, 매출액, 폐업률 필드가 명시되어 있지 않다. 데이터에 없는 정보를 추정해 생성하지 않는다. 평균 폐업 개월 수를 폐업률로 해석하지 않는다.

## 3. 개발 환경

- IDE: VS Code
- 운영체제/터미널: Windows / PowerShell
- 언어: Python
- 분석 환경: Jupyter Notebook (`.ipynb`)
- 가상환경: 프로젝트 루트의 `.venv`
- 주요 패키지: `requests`, `pandas`, `ipykernel`; 추가 패키지는 필요할 때만 설치

### 초기 설정

프로젝트 루트에서 실행한다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install requests pandas ipykernel
python -m ipykernel install --user --name busan-commercial --display-name "Python (Busan Commercial)"
```

VS Code에서 Notebook 커널을 프로젝트 `.venv`의 Python으로 선택한다.

가상환경 활성화 확인:

```powershell
python -c "import sys; print(sys.executable)"
```

출력 경로에 `.venv\Scripts\python.exe`가 포함되어야 한다.

## 4. 권장 디렉터리 구조

```text
project/
├─ .venv/                     # Git 추적 제외
├─ .gitignore
├─ .env.example               # 키 이름만 기록, 실제 값 금지
├─ PROJECT_INSTRUCTIONS.md
├─ notebooks/
│  └─ 01_collect_busan_commercial.ipynb
├─ data/
│  ├─ raw/                    # API 원본 응답
│  └─ processed/              # 정제된 CSV
└─ README.md
```

`.gitignore`에 최소한 `.venv/`, `.env`, `__pycache__/`, `.ipynb_checkpoints/`를 추가한다. API 키를 Notebook 코드, 출력 셀, Git 커밋에 포함하지 않는다.

## 5. 수집·처리 작업 원칙

1. **한 페이지 테스트:** API 인증키와 HTTP 응답, API 결과코드, 응답 형식을 먼저 확인한다.
2. **전체 페이지 수집:** `totalCount`, `numOfRows`, `pageNo`를 활용해 페이지를 순회한다. 문서에 있는 예시 건수를 고정값으로 사용하지 않는다.
3. **오류 처리:** HTTP 오류, API 결과코드 오류, XML/JSON 파싱 실패, 타임아웃을 구분하여 기록한다.
4. **원본 보존:** 가능하면 API 원본 응답을 `data/raw/`에 저장한다.
5. **정제:** 필드명 유지, 숫자형 변환, 결측치·중복값 확인을 수행한다.
6. **검증:** API `totalCount`와 수집 행 수를 비교하고, 중복 판단 기준을 별도로 검토한다. 상권명만으로 무조건 중복 제거하지 않는다.
7. **저장:** `data/processed/busan_commercial_change.csv`로 저장하며 한글 호환을 위해 `utf-8-sig`를 사용한다.
8. **EDA:** 상권 변화 유형 분포, 평균 생존·폐업 개월 수 분포, 이상치·결측치 및 지역 매핑 가능성을 살펴본다.
9. **재현성:** 실행일, 수집 시점, 요청 파라미터, 응답 건수를 기록한다.
10. **이용 조건:** 공공데이터포털의 활용 조건과 호출 제한을 준수한다.

## 6. 프로젝트 해석상의 제한

- 상권 변화지표는 **지역 지원 우선순위 판단을 위한 후보 지표**이지, 금융위험을 단독으로 확정하는 근거가 아니다.
- 다른 데이터와 결합하려면 상권의 공간적 범위·주소·지역코드 매핑 가능성을 먼저 확인한다.
- 월별 추세, 업종별 취약성, 매출 감소, 폐업률 등은 해당 필드가 있는 별도 데이터 확보 후 분석한다.
- BC카드 상권분석 대시보드의 **대량 원자료 추출 가능성은 아직 검증되지 않았으며**, 유료 데이터마켓 제공 가능성이 있으므로 이 API와 혼동하지 않는다.
- 서울신보 등의 개별 사업자 알림 서비스와 달리, 본 프로젝트는 **상권 단위 자원 배분 우선순위**를 지원하는 데 초점을 둔다.

## 7. AI 코딩 도구 작업 지침

- 사용자에게 **한 번에 한 단계씩** 안내하고, 각 단계의 실행 결과를 확인한 뒤 다음 단계로 진행한다.
- 현재 사용 중인 `.venv`가 있으면 재사용하고, 패키지 설치 전 커널/인터프리터를 확인한다.
- 코드 작성 시 실제 API 응답 구조를 확인하기 전에는 JSON 중첩 구조를 단정하지 않는다.
- 파일 경로는 프로젝트 루트를 기준으로 일관되게 작성한다.
- API 키를 출력하거나 소스 코드에 하드코딩하지 않는다.
- 오류 발생 시 전체 코드를 무작정 교체하기보다 원인을 진단하고 최소한으로 수정한다.
- 확인된 사실, 가설, 아직 검증되지 않은 내용을 명확히 구분한다.
- 데이터 수집 성공 후에만 분석·시각화 단계로 넘어간다.

## 8. 현재 진행 상태

- [x] 공공데이터 API 활용가이드 확보 및 엔드포인트 확인
- [x] VS Code + Jupyter Notebook 활용 방향 결정
- [x] 기존 프로젝트 가상환경이 없음을 확인
- [ ] `.venv` 생성 및 활성화 완료 확인
- [ ] Python 패키지 설치 및 Notebook 커널 연결
- [ ] 공공데이터포털 API 키 발급/활용 승인 확인
- [ ] API 1페이지 테스트
- [ ] 전체 데이터 수집 및 CSV 저장
- [ ] 데이터 품질 점검 및 EDA

**다음 작업:** `.venv` 생성과 활성화 상태부터 확인한다. 사용자가 완료했다고 확인하기 전에는 이후 단계를 완료 처리하지 않는다.
