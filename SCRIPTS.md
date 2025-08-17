# 🚀 프로젝트 스크립트 가이드

이 프로젝트는 npm scripts와 유사한 uv 커스텀 명령어를 제공합니다.

## 📋 사용 가능한 명령어

### 🔧 서버 관련
```bash
# 기본 서버 시작
uv run start

# 개발 서버 시작 (hot reload 포함)
uv run dev

# 프로덕션 서버 시작
uv run serve
```

### 🧪 개발 도구
```bash
# 테스트 실행
uv run test

# 코드 린팅 (ruff)
uv run lint

# 코드 포맷팅 (ruff + black)
uv run format

# 종합 품질 검사 (린팅 + 테스트)
uv run check

# 개발 의존성 설치
uv run install
```

## 🛠️ 설정 방법

이 기능은 `pyproject.toml`의 `[project.scripts]` 섹션에 정의되어 있습니다:

```toml
[project.scripts]
start = "app.server:main"
dev = "app.server:dev_server"
serve = "app.server:prod_server"
test = "app.scripts:test"
lint = "app.scripts:lint"
format = "app.scripts:format_code"
install = "app.scripts:install"
check = "app.scripts:check"
```

## 🎯 npm scripts와의 비교

| npm | uv | 설명 |
|-----|-----|------|
| `npm start` | `uv run start` | 서버 시작 |
| `npm run dev` | `uv run dev` | 개발 서버 |
| `npm test` | `uv run test` | 테스트 실행 |
| `npm run lint` | `uv run lint` | 코드 린팅 |
| `npm run format` | `uv run format` | 코드 포맷팅 |
| `npm install` | `uv run install` | 의존성 설치 |

## 🔍 추가 정보

- 개발 의존성은 자동으로 설치됩니다
- `uv run` 명령어는 프로젝트 가상환경에서 실행됩니다
- 모든 스크립트는 프로젝트 루트에서 실행해야 합니다

## 🚀 시작하기

1. 개발 의존성 설치:
   ```bash
   uv sync --dev
   ```

2. 개발 서버 시작:
   ```bash
   uv run dev
   ```

3. 코드 품질 검사:
   ```bash
   uv run check
   ```