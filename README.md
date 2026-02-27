# 💰 개인 지출 분석 대시보드

Streamlit 기반의 개인 소비 데이터 분석 및 AI 인사이트 제공 웹 애플리케이션입니다.  
CSV/Excel 파일을 업로드하면 지출 패턴 분석, 맞춤형 예산 추천, AI 소비 분석 리포트를 제공합니다.

---

## 📌 프로젝트 목적

- 개인 소비 데이터를 구조화하여 시각적으로 분석
- 전기 대비 / 전년 동월 대비(YoY) 비교 자동화
- 카테고리별 절감 모델링 기반 예산 설계
- GPT 기반 소비 인사이트 자동화
- 월간 리포트 자동 생성 시스템 구현

---

## 🚀 주요 기능

### 1️⃣ 핵심 지표 대시보드
- 총 지출
- 평균 지출
- 최대 지출
- 거래 건수
- 전기 대비 증감률 계산
- 전년 동월(YoY) 비교

---

### 2️⃣ 데이터 필터링
- 연도 선택
- 기간 선택 (달력 기반)
- 카테고리 체크박스 선택
- 결제수단 필터
- 금액 범위 슬라이더

---

### 3️⃣ 시각화 분석
- 카테고리별 지출 도넛 차트
- 월별 지출 추이 라인 차트

---

### 4️⃣ 맞춤형 예산 추천
- 카테고리별 현재 지출 계산
- 권장 예산 자동 산출
- 절감 목표 금액 제시
- 절감률 계산

---

### 5️⃣ AI 소비 분석 (OpenAI 연동)
AI가 다음 항목을 분석합니다:

- 지출 패턴 분석
- 급증/이상 지출 탐지
- 절약 가능 영역 제안
- 다음 달 예산 설계
- 한 줄 요약 제공

---

### 6️⃣ 월간 지출 리포트 생성
리포트 구성:

- 요약 지표
- 전기 대비 변화
- 카테고리 분석
- 상위 지출 5개
- AI 인사이트
- 예산 추천
- Markdown 다운로드 기능

---

## 🛠 기술 스택

- Python
- Streamlit
- Pandas
- Plotly
- OpenAI API

---

## 📂 프로젝트 구조
expense-dashboard/
├── app.py                 # 메인 Streamlit 앱
├── requirements.txt       # 의존성 목록
├── README.md             # 프로젝트 설명
├── data/
      └── expense_all_data.csv   # 샘플 데이터


---

## ⚙️ 실행 방법 (로컬)

### 1. 패키지 설치
pip install -r requirements.txt

### 2. 실행
streamlit run app.py


---

## 🔐 OpenAI API 키 설정
AI 기능 사용 시 필요합니다.

### 로컬 실행 시
환경 변수 설정:
Mac/Linux: export OPENAI_API_KEY=your_api_key
Windows: setx OPENAI_API_KEY "your_api_key"

---

### Streamlit Cloud 배포 시
Settings → Secrets에 아래 입력:
OPENAI_API_KEY = "your_api_key"


---

## 📊 데이터 형식

필수 컬럼:

- date (날짜)
- amount (지출 금액)
- category (카테고리)

선택 컬럼:

- description (지출 설명)
- payment_method (결제수단)

---

## 🔮 향후 개선 계획

- PDF 리포트 자동 생성
- 소비 이상 탐지 모델 추가
- 고정비/변동비 자동 분류
- 모바일 UI 최적화

---

## 📄 라이선스
MIT License
