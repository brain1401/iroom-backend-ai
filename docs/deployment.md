# 배포 가이드

## 🚢 배포 개요

iRoom Backend AI는 다양한 환경에 배포할 수 있도록 설계되었습니다:
- Docker 컨테이너
- Kubernetes
- 클라우드 플랫폼 (AWS, GCP, Azure)
- 전통적인 서버 배포

## 🐳 Docker 배포

### 기본 Docker 배포

#### 1. 이미지 빌드
```bash
# 프로젝트 루트에서
docker build -t iroom-backend-ai:latest .

# 태그 추가
docker tag iroom-backend-ai:latest iroom-backend-ai:v1.0.0
```

#### 2. 컨테이너 실행
```bash
# 기본 실행
docker run -d \
  --name iroom-backend-ai \
  -p 8080:8080 \
  -e GEMINI_API_KEY=your_google_api_key \
  iroom-backend-ai:latest

# 환경변수 파일 사용
docker run -d \
  --name iroom-backend-ai \
  -p 8080:8080 \
  --env-file .env.prod \
  iroom-backend-ai:latest
```

#### 3. 컨테이너 관리
```bash
# 상태 확인
docker ps
docker logs iroom-backend-ai

# 헬스체크
curl http://localhost:8080/health

# 컨테이너 중지/시작
docker stop iroom-backend-ai
docker start iroom-backend-ai

# 컨테이너 재시작
docker restart iroom-backend-ai
```

### Docker Compose 배포

#### `docker-compose.yml`
```yaml
version: '3.8'

services:
  iroom-backend-ai:
    build: .
    container_name: iroom-backend-ai
    ports:
      - "8080:8080"
    environment:
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - GEMINI_MODEL=gemini-2.5-pro
      - HOST=0.0.0.0
      - PORT=8080
      - DEBUG=false
      - LOG_LEVEL=INFO
      - REQUIRE_API_KEY=true
      - RATE_LIMIT_ENABLED=true
    env_file:
      - .env.prod
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s

  # Redis (선택적 - Rate Limiting용)
  redis:
    image: redis:7-alpine
    container_name: redis
    ports:
      - "6379:6379"
    restart: unless-stopped
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes

volumes:
  redis_data:
```

#### 실행
```bash
# 백그라운드 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f

# 스케일링
docker-compose up -d --scale iroom-backend-ai=3

# 중지
docker-compose down
```

## ☸️ Kubernetes 배포

### 기본 Kubernetes 매니페스트

#### `k8s/namespace.yaml`
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: iroom-backend-ai
```

#### `k8s/configmap.yaml`
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: iroom-backend-ai-config
  namespace: iroom-backend-ai
data:
  GEMINI_MODEL: "gemini-2.5-pro"
  HOST: "0.0.0.0"
  PORT: "8080"
  DEBUG: "false"
  LOG_LEVEL: "INFO"
  REQUIRE_API_KEY: "true"
  RATE_LIMIT_ENABLED: "true"
  REDIS_ENABLED: "true"
  REDIS_URL: "redis://redis-service:6379"
```

#### `k8s/secret.yaml`
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: iroom-backend-ai-secrets
  namespace: iroom-backend-ai
type: Opaque
data:
  GEMINI_API_KEY: <base64-encoded-api-key>
  VALID_API_KEYS: <base64-encoded-json-array>
```

#### `k8s/deployment.yaml`
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: iroom-backend-ai
  namespace: iroom-backend-ai
  labels:
    app: iroom-backend-ai
spec:
  replicas: 3
  selector:
    matchLabels:
      app: iroom-backend-ai
  template:
    metadata:
      labels:
        app: iroom-backend-ai
    spec:
      containers:
      - name: iroom-backend-ai
        image: iroom-backend-ai:latest
        ports:
        - containerPort: 8080
        envFrom:
        - configMapRef:
            name: iroom-backend-ai-config
        - secretRef:
            name: iroom-backend-ai-secrets
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            cpu: 500m
            memory: 512Mi
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 5
          timeoutSeconds: 3
          successThreshold: 1
          failureThreshold: 3
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 15"]
```

#### `k8s/service.yaml`
```yaml
apiVersion: v1
kind: Service
metadata:
  name: iroom-backend-ai-service
  namespace: iroom-backend-ai
spec:
  selector:
    app: iroom-backend-ai
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8080
  type: ClusterIP
```

#### `k8s/ingress.yaml`
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: iroom-backend-ai-ingress
  namespace: iroom-backend-ai
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  tls:
  - hosts:
    - api.yourdomain.com
    secretName: iroom-backend-ai-tls
  rules:
  - host: api.yourdomain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: iroom-backend-ai-service
            port:
              number: 80
```

### 배포 실행
```bash
# 네임스페이스 생성
kubectl apply -f k8s/namespace.yaml

# Secret 생성 (base64 인코딩 필요)
echo -n "your_gemini_api_key" | base64
kubectl apply -f k8s/secret.yaml

# ConfigMap 적용
kubectl apply -f k8s/configmap.yaml

# 애플리케이션 배포
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml

# 배포 상태 확인
kubectl get pods -n iroom-backend-ai
kubectl get services -n iroom-backend-ai
kubectl get ingress -n iroom-backend-ai
```

### Helm 차트 (선택적)

#### `helm/Chart.yaml`
```yaml
apiVersion: v2
name: iroom-backend-ai
description: AI backend service using Google Gemini
type: application
version: 1.0.0
appVersion: "1.0.0"
```

#### `helm/values.yaml`
```yaml
replicaCount: 3

image:
  repository: iroom-backend-ai
  tag: latest
  pullPolicy: IfNotPresent

service:
  type: ClusterIP
  port: 80
  targetPort: 8080

ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: api.yourdomain.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: iroom-backend-ai-tls
      hosts:
        - api.yourdomain.com

config:
  geminiModel: "gemini-2.5-pro"
  debug: false
  logLevel: INFO
  requireApiKey: true
  rateLimitEnabled: true

secrets:
  geminiApiKey: ""
  validApiKeys: []

resources:
  requests:
    cpu: 100m
    memory: 256Mi
  limits:
    cpu: 500m
    memory: 512Mi

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
```

#### Helm 배포
```bash
# 차트 설치
helm install iroom-backend-ai ./helm \
  --namespace iroom-backend-ai \
  --create-namespace \
  --set secrets.geminiApiKey="your_api_key"

# 업그레이드
helm upgrade iroom-backend-ai ./helm \
  --namespace iroom-backend-ai

# 상태 확인
helm status iroom-backend-ai -n iroom-backend-ai
```

## ☁️ 클라우드 배포

### AWS ECS

#### `aws/task-definition.json`
```json
{
  "family": "iroom-backend-ai",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "arn:aws:iam::account:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::account:role/ecsTaskRole",
  "containerDefinitions": [
    {
      "name": "iroom-backend-ai",
      "image": "your-account.dkr.ecr.region.amazonaws.com/iroom-backend-ai:latest",
      "portMappings": [
        {
          "containerPort": 8080,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {
          "name": "HOST",
          "value": "0.0.0.0"
        },
        {
          "name": "PORT",
          "value": "8080"
        }
      ],
      "secrets": [
        {
          "name": "GEMINI_API_KEY",
          "valueFrom": "arn:aws:secretsmanager:region:account:secret:gemini-api-key"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/iroom-backend-ai",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      },
      "healthCheck": {
        "command": [
          "CMD-SHELL",
          "curl -f http://localhost:8080/health || exit 1"
        ],
        "interval": 30,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 60
      }
    }
  ]
}
```

#### AWS 배포 스크립트
```bash
#!/bin/bash

# ECR 로그인
aws ecr get-login-password --region us-east-1 | \
docker login --username AWS --password-stdin \
your-account.dkr.ecr.us-east-1.amazonaws.com

# 이미지 빌드 및 푸시
docker build -t iroom-backend-ai .
docker tag iroom-backend-ai:latest \
your-account.dkr.ecr.us-east-1.amazonaws.com/iroom-backend-ai:latest
docker push your-account.dkr.ecr.us-east-1.amazonaws.com/iroom-backend-ai:latest

# 태스크 정의 등록
aws ecs register-task-definition \
  --cli-input-json file://aws/task-definition.json

# 서비스 업데이트
aws ecs update-service \
  --cluster iroom-cluster \
  --service iroom-backend-ai-service \
  --force-new-deployment
```

### Google Cloud Run

#### `gcp/cloudbuild.yaml`
```yaml
steps:
  # 이미지 빌드
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$PROJECT_ID/iroom-backend-ai', '.']
  
  # 이미지 푸시
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/iroom-backend-ai']
  
  # Cloud Run 배포
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
    - 'run'
    - 'deploy'
    - 'iroom-backend-ai'
    - '--image'
    - 'gcr.io/$PROJECT_ID/iroom-backend-ai'
    - '--region'
    - 'us-central1'
    - '--platform'
    - 'managed'
    - '--allow-unauthenticated'
    - '--set-env-vars'
    - 'PORT=8080'
    - '--memory'
    - '1Gi'
    - '--cpu'
    - '1'
    - '--max-instances'
    - '10'

images:
  - 'gcr.io/$PROJECT_ID/iroom-backend-ai'
```

#### 수동 Cloud Run 배포
```bash
# 프로젝트 설정
gcloud config set project your-project-id

# 이미지 빌드 및 푸시
gcloud builds submit --tag gcr.io/your-project-id/iroom-backend-ai

# Cloud Run 배포
gcloud run deploy iroom-backend-ai \
  --image gcr.io/your-project-id/iroom-backend-ai \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --max-instances 10 \
  --set-env-vars PORT=8080 \
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest
```

## 🔧 배포 설정

### 환경별 설정 파일

#### `.env.prod` (프로덕션)
```bash
# 앱 설정
DEBUG=false
LOG_LEVEL=WARNING
APP_NAME="iRoom Backend AI"
APP_VERSION="1.0.0"

# 서버 설정
HOST=0.0.0.0
PORT=8080
WORKERS=4

# Gemini 설정
GEMINI_MODEL=gemini-2.5-pro
GEMINI_TEMPERATURE=0.7
GEMINI_MAX_TOKENS=32000

# 보안 설정
REQUIRE_API_KEY=true
API_KEY_HEADER=x-api-key

# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS_PER_MINUTE=15
RATE_LIMIT_TOKENS_PER_DAY=1000000

# CORS (프로덕션 도메인만)
CORS_ORIGINS=["https://yourdomain.com"]
CORS_ALLOW_CREDENTIALS=true

# Redis (분산 Rate Limiting)
REDIS_ENABLED=true
REDIS_URL=redis://redis:6379

# 헬스체크
HEALTH_CHECK_ENABLED=true
```

#### `.env.staging` (스테이징)
```bash
# 프로덕션과 유사하지만 더 관대한 설정
DEBUG=false
LOG_LEVEL=INFO
REQUIRE_API_KEY=true
RATE_LIMIT_REQUESTS_PER_MINUTE=60
CORS_ORIGINS=["https://staging.yourdomain.com", "http://localhost:3000"]
```

## 📊 모니터링 및 로깅

### 로그 수집

#### Docker 로그
```bash
# 로그 확인
docker logs iroom-backend-ai -f

# 로그 로테이션 설정
docker run -d \
  --log-driver json-file \
  --log-opt max-size=10m \
  --log-opt max-file=3 \
  iroom-backend-ai:latest
```

#### Kubernetes 로그
```bash
# Pod 로그 확인
kubectl logs -f deployment/iroom-backend-ai -n iroom-backend-ai

# 로그 집계 (Fluentd/Fluent Bit)
```

### 헬스체크 및 모니터링

#### Prometheus 메트릭 (향후 확장)
```python
# app/middleware/metrics.py
from prometheus_client import Counter, Histogram, generate_latest

# 메트릭 정의
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint'])
REQUEST_DURATION = Histogram('http_request_duration_seconds', 'HTTP request duration')

# FastAPI 통합
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    
    REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path).inc()
    REQUEST_DURATION.observe(duration)
    
    return response

# 메트릭 엔드포인트
@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")
```

#### Grafana 대시보드
```json
{
  "dashboard": {
    "title": "iRoom Backend AI",
    "panels": [
      {
        "title": "Request Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(http_requests_total[5m])"
          }
        ]
      },
      {
        "title": "Response Time",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))"
          }
        ]
      },
      {
        "title": "Error Rate",
        "type": "singlestat",
        "targets": [
          {
            "expr": "rate(http_requests_total{status=~\"5..\"}[5m])"
          }
        ]
      }
    ]
  }
}
```

## 🛡️ 보안 고려사항

### 컨테이너 보안
```dockerfile
# 보안 강화된 Dockerfile
FROM python:3.11-slim

# 보안 업데이트
RUN apt-get update && apt-get upgrade -y && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 비권한 사용자 생성
RUN groupadd -r appuser && useradd -r -g appuser appuser

# 애플리케이션 파일 복사
WORKDIR /app
COPY . .
RUN chown -R appuser:appuser /app

# 비권한 사용자로 실행
USER appuser

# 포트 노출
EXPOSE 8080

# 헬스체크
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

CMD ["uv", "run", "uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8080"]
```

### 네트워크 보안
```yaml
# Kubernetes NetworkPolicy
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: iroom-backend-ai-netpol
  namespace: iroom-backend-ai
spec:
  podSelector:
    matchLabels:
      app: iroom-backend-ai
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: ingress-nginx
    ports:
    - protocol: TCP
      port: 8080
  egress:
  - to: []
    ports:
    - protocol: TCP
      port: 443  # HTTPS to external APIs
    - protocol: TCP
      port: 53   # DNS
    - protocol: UDP
      port: 53   # DNS
```

## 🔄 CI/CD 파이프라인

### GitHub Actions

#### `.github/workflows/deploy.yml`
```yaml
name: Deploy to Production

on:
  push:
    branches: [main]
  release:
    types: [published]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    
    - name: Install uv
      uses: astral-sh/setup-uv@v1
      
    - name: Set up Python
      run: uv python install 3.11
      
    - name: Install dependencies
      run: uv sync
      
    - name: Run tests
      run: uv run pytest
      
    - name: Run linting
      run: uv run ruff check
      
    - name: Run formatting check
      run: uv run black --check .

  build-and-push:
    needs: test
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    
    steps:
    - uses: actions/checkout@v4
    
    - name: Log in to Container Registry
      uses: docker/login-action@v3
      with:
        registry: ${{ env.REGISTRY }}
        username: ${{ github.actor }}
        password: ${{ secrets.GITHUB_TOKEN }}
    
    - name: Extract metadata
      id: meta
      uses: docker/metadata-action@v5
      with:
        images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
        tags: |
          type=ref,event=branch
          type=ref,event=pr
          type=semver,pattern={{version}}
          type=semver,pattern={{major}}.{{minor}}
    
    - name: Build and push Docker image
      uses: docker/build-push-action@v5
      with:
        context: .
        push: true
        tags: ${{ steps.meta.outputs.tags }}
        labels: ${{ steps.meta.outputs.labels }}

  deploy:
    needs: build-and-push
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    
    steps:
    - name: Deploy to Kubernetes
      run: |
        # kubectl 명령어로 배포
        echo "Deploying to production..."
```

## 📋 배포 체크리스트

### 배포 전 확인사항
- [ ] 모든 테스트 통과
- [ ] 보안 스캔 완료
- [ ] 환경변수 설정 확인
- [ ] API 키 및 Secret 설정
- [ ] 리소스 제한 설정
- [ ] 헬스체크 구성
- [ ] 로깅 설정
- [ ] 모니터링 구성
- [ ] 백업 계획 수립

### 배포 후 확인사항
- [ ] 헬스체크 엔드포인트 응답
- [ ] API 기능 정상 작동
- [ ] 로그 정상 출력
- [ ] 메트릭 수집 확인
- [ ] 성능 테스트 실행
- [ ] 장애 복구 절차 테스트

---

**성공적인 배포를 위해 이 가이드를 단계별로 따라하시기 바랍니다! 🚀**