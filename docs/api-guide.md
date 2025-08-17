# API 사용 가이드

## 🚀 빠른 시작

### 서버 실행
```bash
# 개발 서버
uv run dev

# 프로덕션 서버  
uv run serve
```

### API 문서 확인
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 📋 API 엔드포인트 개요

| 엔드포인트 | 메서드 | 설명 | 인증 필요 |
|-----------|--------|------|----------|
| `/gemini/invoke` | POST | 단일 텍스트 생성 요청 | 선택적 |
| `/gemini/batch` | POST | 배치 텍스트 생성 요청 | 선택적 |
| `/gemini/stream` | POST | 스트리밍 텍스트 생성 | 선택적 |
| `/gemini/health` | GET | Gemini API 상태 확인 | 없음 |
| `/health` | GET | 전체 서비스 상태 확인 | 없음 |
| `/docs` | GET | API 문서 (Swagger) | 없음 |

## 🔑 인증

### API 키 설정 (선택적)

환경변수로 인증 활성화:
```bash
export REQUIRE_API_KEY=true
export VALID_API_KEYS=["your-api-key-1", "your-api-key-2"]
export API_KEY_HEADER="x-api-key"
```

### 인증 헤더 사용
```bash
curl -H "x-api-key: your-api-key" \
     -X POST http://localhost:8000/gemini/invoke \
     -H "Content-Type: application/json" \
     -d '{"input": {"input": "Hello, world!"}}'
```

## 🎯 주요 API 사용법

### 1. 단일 요청 (`/gemini/invoke`)

#### 기본 사용법
```bash
curl -X POST http://localhost:8000/gemini/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "input": "파이썬으로 간단한 웹 크롤러를 만드는 방법을 알려줘"
    }
  }'
```

#### 응답 예시
```json
{
  "output": {
    "output": "파이썬으로 웹 크롤러를 만드는 방법을 설명드리겠습니다...\n\n1. 필요한 라이브러리 설치\n```bash\npip install requests beautifulsoup4\n```\n\n2. 기본 크롤러 코드\n```python\nimport requests\nfrom bs4 import BeautifulSoup\n\ndef crawl_website(url):\n    response = requests.get(url)\n    soup = BeautifulSoup(response.content, 'html.parser')\n    return soup\n```"
  }
}
```

#### Python 클라이언트 사용
```python
import requests

# 기본 요청
response = requests.post(
    "http://localhost:8000/gemini/invoke",
    json={"input": {"input": "안녕하세요! 오늘 날씨가 어때요?"}}
)

result = response.json()
print(result["output"]["output"])
```

#### LangServe 클라이언트 사용
```python
from langserve import RemoteRunnable

# RemoteRunnable로 연결
gemini = RemoteRunnable("http://localhost:8000/gemini/")

# 직접 호출 (더 간단)
result = gemini.invoke({"input": "머신러닝이 뭔가요?"})
print(result["output"])

# 비동기 호출
import asyncio

async def async_call():
    result = await gemini.ainvoke({"input": "AI의 미래는?"})
    print(result["output"])

asyncio.run(async_call())
```

### 2. 배치 요청 (`/gemini/batch`)

#### 기본 사용법
```bash
curl -X POST http://localhost:8000/gemini/batch \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": [
      {"input": "1+1은 무엇인가요?"},
      {"input": "파이썬이 뭔가요?"},
      {"input": "AI란 무엇인가요?"}
    ]
  }'
```

#### Python 클라이언트
```python
import requests

# 여러 질문을 한 번에 처리
questions = [
    {"input": "React란 무엇인가요?"},
    {"input": "Node.js의 장점은?"},
    {"input": "RESTful API 설계 원칙은?"}
]

response = requests.post(
    "http://localhost:8000/gemini/batch",
    json={"inputs": questions}
)

results = response.json()["outputs"]
for i, result in enumerate(results):
    print(f"질문 {i+1}: {result['output']}")
```

#### LangServe 클라이언트
```python
from langserve import RemoteRunnable

gemini = RemoteRunnable("http://localhost:8000/gemini/")

# 배치 처리
questions = [
    {"input": "파이썬의 특징은?"},
    {"input": "데이터베이스란?"},
    {"input": "클라우드 컴퓨팅이란?"}
]

results = gemini.batch(questions)
for result in results:
    print(result["output"])
```

### 3. 스트리밍 요청 (`/gemini/stream`)

#### Server-Sent Events (SSE)
```bash
curl -X POST http://localhost:8000/gemini/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"input": {"input": "긴 소설을 써주세요"}}'
```

#### Python으로 스트리밍 받기
```python
import requests

response = requests.post(
    "http://localhost:8000/gemini/stream",
    json={"input": {"input": "창의적인 이야기를 들려주세요"}},
    stream=True,
    headers={"Accept": "text/event-stream"}
)

for line in response.iter_lines():
    if line:
        print(line.decode('utf-8'))
```

#### LangServe 클라이언트로 스트리밍
```python
from langserve import RemoteRunnable

gemini = RemoteRunnable("http://localhost:8000/gemini/")

# 스트리밍으로 실시간 응답 받기
for chunk in gemini.stream({"input": "AI 기술의 발전 과정을 설명해주세요"}):
    print(chunk["output"], end="", flush=True)
```

#### 비동기 스트리밍
```python
import asyncio
from langserve import RemoteRunnable

async def stream_response():
    gemini = RemoteRunnable("http://localhost:8000/gemini/")
    
    async for chunk in gemini.astream({"input": "미래 기술 트렌드는?"}):
        print(chunk["output"], end="", flush=True)

asyncio.run(stream_response())
```

## 🔍 헬스체크

### 전체 서비스 상태
```bash
curl http://localhost:8000/health
```

#### 응답 예시
```json
{
  "status": "healthy",
  "service": "iroom-backend-ai",
  "version": "1.0.0",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

### Gemini API 상태
```bash
curl http://localhost:8000/gemini/health
```

#### 응답 예시
```json
{
  "status": "healthy",
  "service": "gemini"
}
```

## ⚡ Rate Limiting

### 제한사항
- **Free Tier**: 15 requests/minute, 1M tokens/day
- **Paid Tier**: 60 requests/minute, 10M tokens/day

### Rate Limit 헤더
```http
HTTP/1.1 200 OK
X-RateLimit-Limit: 15
X-RateLimit-Remaining: 14
X-RateLimit-Reset: 1640995200
```

### Rate Limit 초과 시
```json
{
  "detail": "Rate limit exceeded. Try again later."
}
```

## 🚨 에러 처리

### 일반적인 HTTP 상태 코드

| 코드 | 의미 | 설명 |
|------|------|------|
| 200 | OK | 성공적인 요청 |
| 400 | Bad Request | 잘못된 요청 형식 |
| 401 | Unauthorized | API 키 인증 실패 |
| 429 | Too Many Requests | Rate limit 초과 |
| 500 | Internal Server Error | 서버 내부 오류 |
| 503 | Service Unavailable | Gemini API 응답 없음 |

### 에러 응답 형식
```json
{
  "detail": "Error description",
  "error_code": "SPECIFIC_ERROR_CODE",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

### Python에서 에러 처리
```python
import requests
from requests.exceptions import RequestException

def safe_api_call(prompt):
    try:
        response = requests.post(
            "http://localhost:8000/gemini/invoke",
            json={"input": {"input": prompt}},
            timeout=30
        )
        response.raise_for_status()
        return response.json()["output"]["output"]
        
    except requests.exceptions.HTTPError as e:
        if response.status_code == 429:
            print("Rate limit exceeded. Please wait.")
        elif response.status_code == 401:
            print("Authentication failed. Check your API key.")
        else:
            print(f"HTTP error: {e}")
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
    except KeyError:
        print("Unexpected response format")
    
    return None

# 사용 예시
result = safe_api_call("안녕하세요!")
if result:
    print(result)
```

## 🔧 고급 사용법

### 1. 커스텀 헤더 설정
```python
headers = {
    "x-api-key": "your-api-key",
    "x-request-id": "unique-request-id",
    "user-agent": "MyApp/1.0"
}

response = requests.post(
    "http://localhost:8000/gemini/invoke",
    json={"input": {"input": "Hello"}},
    headers=headers
)
```

### 2. 타임아웃 설정
```python
# 30초 타임아웃
response = requests.post(
    "http://localhost:8000/gemini/invoke",
    json={"input": {"input": "복잡한 질문..."}},
    timeout=30
)
```

### 3. 세션 사용 (연결 재사용)
```python
import requests

session = requests.Session()
session.headers.update({"x-api-key": "your-api-key"})

# 여러 요청에서 세션 재사용
for question in questions:
    response = session.post(
        "http://localhost:8000/gemini/invoke",
        json={"input": {"input": question}}
    )
    print(response.json()["output"]["output"])
```

### 4. 비동기 클라이언트 (aiohttp)
```python
import aiohttp
import asyncio

async def async_gemini_call(prompt):
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "http://localhost:8000/gemini/invoke",
            json={"input": {"input": prompt}},
            headers={"x-api-key": "your-api-key"}
        ) as response:
            result = await response.json()
            return result["output"]["output"]

# 병렬 처리
async def parallel_calls():
    prompts = ["질문1", "질문2", "질문3"]
    tasks = [async_gemini_call(prompt) for prompt in prompts]
    results = await asyncio.gather(*tasks)
    return results

results = asyncio.run(parallel_calls())
```

## 📊 모니터링 및 로깅

### 요청 추적
모든 요청은 구조화된 로그로 기록됩니다:
```json
{
  "timestamp": "2024-01-01T00:00:00Z",
  "level": "INFO",
  "event": "request_processed",
  "method": "POST",
  "path": "/gemini/invoke",
  "status_code": 200,
  "duration_ms": 1234,
  "request_id": "req_123"
}
```

### 요청 ID 추가
```python
import uuid

request_id = str(uuid.uuid4())
response = requests.post(
    "http://localhost:8000/gemini/invoke",
    json={"input": {"input": "Hello"}},
    headers={"x-request-id": request_id}
)
```

## 🛠️ 문제 해결

### 자주 발생하는 문제

#### 1. 연결 오류
```bash
# 서버가 실행 중인지 확인
curl http://localhost:8000/health
```

#### 2. 인증 오류
```bash
# API 키 확인
echo $REQUIRE_API_KEY
echo $VALID_API_KEYS
```

#### 3. Rate Limit 오류
- 요청 간격 조절
- Paid Tier 사용 고려

#### 4. 타임아웃 오류
- 복잡한 질문의 경우 타임아웃 증가
- 스트리밍 API 사용 고려

### 디버깅 팁
```python
# 상세 로깅 활성화
import logging
logging.basicConfig(level=logging.DEBUG)

# 응답 헤더 확인
response = requests.post(...)
print("Status:", response.status_code)
print("Headers:", response.headers)
print("Response:", response.text)
```

---

**이 가이드를 통해 iRoom Backend AI API를 효과적으로 활용하시기 바랍니다!**