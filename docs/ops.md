# מדריך תפעול ודיפלוי 🚀

מדריך מקיף לפריסת המערכת בסביבות שונות, ניטור, תחזוקה ופתרון בעיות.

## סביבות פריסה

### סקירת סביבות

| סביבה | מטרה | URL | Branch |
|-------|------|-----|--------|
| **Development** | פיתוח מקומי | http://localhost:8000 | feature/* |
| **Staging** | בדיקות pre-prod | https://staging.animal-rescue.com | develop |
| **Production** | סביבת ייצור | https://animal-rescue.com | main |

## פריסה ב-Render 🎯

### הגדרת שירותים

#### 1. Web Service (API + Bot)

```yaml
# render.yaml
services:
  - type: web
    name: animal-rescue-api
    runtime: python
    region: frankfurt
    plan: standard
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: ENVIRONMENT
        value: production
      - key: TELEGRAM_BOT_TOKEN
        sync: false
      - key: DATABASE_URL
        fromDatabase:
          name: animal-rescue-db
          property: connectionString
      - key: REDIS_URL
        fromService:
          type: redis
          name: animal-rescue-redis
          property: connectionString
    healthCheckPath: /health
    autoDeploy: true
```

#### 2. Background Workers

```yaml
  - type: worker
    name: animal-rescue-workers
    runtime: python
    region: frankfurt
    plan: standard
    buildCommand: pip install -r requirements.txt
    startCommand: python -c "from app.workers.manager import run_workers_cli; run_workers_cli()"
    envVars:
      - key: ENABLE_WORKERS
        value: true
      - key: WORKER_PROCESSES
        value: 4
      - key: DATABASE_URL
        fromDatabase:
          name: animal-rescue-db
          property: connectionString
      - key: REDIS_URL
        fromService:
          type: redis
          name: animal-rescue-redis
          property: connectionString
```

#### 3. מסדי נתונים

```yaml
databases:
  - name: animal-rescue-db
    plan: standard
    region: frankfurt
    databaseName: animal_rescue
    user: animal_rescue_user
    postgresMajorVersion: 15

services:
  - type: redis
    name: animal-rescue-redis
    plan: standard
    region: frankfurt
    maxmemoryPolicy: allkeys-lru
```

### Deploy Script

```bash
#!/bin/bash
# scripts/deploy_render.sh

echo "🚀 Starting Render deployment..."

# Check environment
if [ "$1" != "staging" ] && [ "$1" != "production" ]; then
    echo "Usage: ./deploy_render.sh [staging|production]"
    exit 1
fi

ENV=$1
SERVICE_NAME="animal-rescue-$ENV"

# Run tests
echo "🧪 Running tests..."
pytest tests/ || exit 1

# Build and push
echo "📦 Building application..."
render deploy --service $SERVICE_NAME

# Run migrations
echo "🗄️ Running database migrations..."
render exec --service $SERVICE_NAME -- alembic upgrade head

# Health check
echo "❤️ Checking service health..."
curl -f https://$SERVICE_NAME.onrender.com/health || exit 1

echo "✅ Deployment complete!"
```

## פריסה ב-Docker 🐳

### Dockerfile

```dockerfile
# Dockerfile
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY alembic.ini .
COPY scripts/ ./scripts/

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health').raise_for_status()"

# Start command
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:password@postgres:5432/animal_rescue
      - REDIS_URL=redis://redis:6379
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - WEBHOOK_HOST=${WEBHOOK_HOST}
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ./uploads:/app/uploads
    restart: unless-stopped

  worker:
    build: .
    command: python -c "from app.workers.manager import run_workers_cli; run_workers_cli()"
    environment:
      - DATABASE_URL=postgresql://user:password@postgres:5432/animal_rescue
      - REDIS_URL=redis://redis:6379
      - ENABLE_WORKERS=true
    depends_on:
      - postgres
      - redis
    restart: unless-stopped

  postgres:
    image: postgis/postgis:15-3.3
    environment:
      - POSTGRES_DB=animal_rescue
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user -d animal_rescue"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
    depends_on:
      - api
    restart: unless-stopped

volumes:
  postgres_data:
  redis_data:
```

### Nginx Configuration

```nginx
# nginx.conf
events {
    worker_connections 1024;
}

http {
    upstream api {
        least_conn;
        server api:8000 max_fails=3 fail_timeout=30s;
    }

    server {
        listen 80;
        server_name animal-rescue.com;
        return 301 https://$server_name$request_uri;
    }

    server {
        listen 443 ssl http2;
        server_name animal-rescue.com;

        ssl_certificate /etc/nginx/ssl/cert.pem;
        ssl_certificate_key /etc/nginx/ssl/key.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;

        client_max_body_size 50M;

        location / {
            proxy_pass http://api;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            
            # WebSocket support
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            
            # Timeouts
            proxy_connect_timeout 60s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }

        location /static {
            alias /app/static;
            expires 30d;
            add_header Cache-Control "public, immutable";
        }
    }
}
```

## Kubernetes Deployment ☸️

### Deployment Manifest

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: animal-rescue-api
  namespace: production
spec:
  replicas: 3
  selector:
    matchLabels:
      app: animal-rescue-api
  template:
    metadata:
      labels:
        app: animal-rescue-api
    spec:
      containers:
      - name: api
        image: animal-rescue:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: animal-rescue-secrets
              key: database-url
        - name: REDIS_URL
          valueFrom:
            secretKeyRef:
              name: animal-rescue-secrets
              key: redis-url
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: animal-rescue-api
  namespace: production
spec:
  selector:
    app: animal-rescue-api
  ports:
  - port: 80
    targetPort: 8000
  type: LoadBalancer
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: animal-rescue-api-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: animal-rescue-api
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

## משתני סביבה 🔐

### Production Environment

```bash
# .env.production
# === Core Settings ===
ENVIRONMENT=production
DEBUG=false
SECRET_KEY=<strong-random-key>
ALLOWED_HOSTS=animal-rescue.com,www.animal-rescue.com

# === Database ===
DATABASE_URL=postgresql://user:password@db.example.com:5432/animal_rescue
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=40

# === Redis ===
REDIS_URL=redis://:password@redis.example.com:6379/0
REDIS_MAX_CONNECTIONS=100

# === Telegram Bot ===
TELEGRAM_BOT_TOKEN=<bot-token>
WEBHOOK_HOST=https://animal-rescue.com
TELEGRAM_WEBHOOK_SECRET=<webhook-secret>

# === Google APIs ===
GOOGLE_PLACES_API_KEY=<api-key>
GOOGLE_GEOCODING_API_KEY=<api-key>

# === Twilio ===
TWILIO_ACCOUNT_SID=<account-sid>
TWILIO_AUTH_TOKEN=<auth-token>
TWILIO_FROM_NUMBER=+972501234567
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886

# === Email ===
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASSWORD=<sendgrid-api-key>
SMTP_FROM=noreply@animal-rescue.com

# === Storage ===
S3_BUCKET=animal-rescue-uploads
S3_ACCESS_KEY=<access-key>
S3_SECRET_KEY=<secret-key>
S3_REGION=eu-central-1

# === Monitoring ===
SENTRY_DSN=https://<key>@sentry.io/<project>
PROMETHEUS_ENABLED=true
GRAFANA_API_KEY=<api-key>

# === Security ===
CORS_ORIGINS=https://animal-rescue.com,https://app.animal-rescue.com
JWT_SECRET_KEY=<jwt-secret>
JWT_ALGORITHM=RS256
RATE_LIMIT=100/minute
```

## ניטור ולוגים 📊

### Prometheus Metrics

```python
# app/core/metrics.py
from prometheus_client import Counter, Histogram, Gauge, generate_latest
import time

# Metrics
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

request_duration_seconds = Histogram(
    'request_duration_seconds',
    'HTTP request duration',
    ['method', 'endpoint']
)

active_reports = Gauge(
    'active_reports',
    'Number of active reports',
    ['status']
)

# Middleware
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start_time = time.time()
    
    response = await call_next(request)
    
    duration = time.time() - start_time
    http_requests_total.labels(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code
    ).inc()
    
    request_duration_seconds.labels(
        method=request.method,
        endpoint=request.url.path
    ).observe(duration)
    
    return response

# Metrics endpoint
@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")
```

### Grafana Dashboard

```json
{
  "dashboard": {
    "title": "Animal Rescue Bot",
    "panels": [
      {
        "title": "Request Rate",
        "targets": [
          {
            "expr": "rate(http_requests_total[5m])"
          }
        ]
      },
      {
        "title": "Response Time",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, request_duration_seconds_bucket)"
          }
        ]
      },
      {
        "title": "Active Reports",
        "targets": [
          {
            "expr": "active_reports"
          }
        ]
      },
      {
        "title": "Error Rate",
        "targets": [
          {
            "expr": "rate(http_requests_total{status=~'5..'}[5m])"
          }
        ]
      }
    ]
  }
}
```

### ELK Stack Setup

```yaml
# docker-compose.elk.yml
version: '3.8'

services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.11.0
    environment:
      - discovery.type=single-node
      - "ES_JAVA_OPTS=-Xms512m -Xmx512m"
    volumes:
      - es_data:/usr/share/elasticsearch/data
    ports:
      - "9200:9200"

  logstash:
    image: docker.elastic.co/logstash/logstash:8.11.0
    volumes:
      - ./logstash.conf:/usr/share/logstash/pipeline/logstash.conf
    depends_on:
      - elasticsearch

  kibana:
    image: docker.elastic.co/kibana/kibana:8.11.0
    environment:
      - ELASTICSEARCH_HOSTS=http://elasticsearch:9200
    ports:
      - "5601:5601"
    depends_on:
      - elasticsearch

volumes:
  es_data:
```

### Logstash Configuration

```ruby
# logstash.conf
input {
  tcp {
    port => 5000
    codec => json
  }
}

filter {
  if [level] == "ERROR" {
    mutate {
      add_tag => ["error"]
    }
  }
  
  geoip {
    source => "client_ip"
    target => "geoip"
  }
}

output {
  elasticsearch {
    hosts => ["elasticsearch:9200"]
    index => "animal-rescue-%{+YYYY.MM.dd}"
  }
  
  if "error" in [tags] {
    email {
      to => "alerts@animal-rescue.com"
      subject => "Error Alert: %{message}"
    }
  }
}
```

## גיבוי ושחזור 💾

### אסטרטגיית גיבוי

```bash
#!/bin/bash
# scripts/backup.sh

# Configuration
BACKUP_DIR="/backups"
DATE=$(date +%Y%m%d_%H%M%S)
S3_BUCKET="animal-rescue-backups"

# Database backup
echo "📦 Backing up database..."
pg_dump $DATABASE_URL | gzip > $BACKUP_DIR/db_$DATE.sql.gz

# Redis backup
echo "📦 Backing up Redis..."
redis-cli --rdb $BACKUP_DIR/redis_$DATE.rdb

# Files backup
echo "📦 Backing up uploaded files..."
tar -czf $BACKUP_DIR/files_$DATE.tar.gz /app/uploads

# Upload to S3
echo "☁️ Uploading to S3..."
aws s3 cp $BACKUP_DIR/db_$DATE.sql.gz s3://$S3_BUCKET/db/
aws s3 cp $BACKUP_DIR/redis_$DATE.rdb s3://$S3_BUCKET/redis/
aws s3 cp $BACKUP_DIR/files_$DATE.tar.gz s3://$S3_BUCKET/files/

# Cleanup old local backups (keep 7 days)
find $BACKUP_DIR -type f -mtime +7 -delete

echo "✅ Backup completed!"
```

### שחזור מגיבוי

```bash
#!/bin/bash
# scripts/restore.sh

if [ -z "$1" ]; then
    echo "Usage: ./restore.sh YYYY-MM-DD"
    exit 1
fi

DATE=$1
S3_BUCKET="animal-rescue-backups"

# Download from S3
echo "📥 Downloading backups..."
aws s3 cp s3://$S3_BUCKET/db/db_$DATE.sql.gz /tmp/
aws s3 cp s3://$S3_BUCKET/redis/redis_$DATE.rdb /tmp/
aws s3 cp s3://$S3_BUCKET/files/files_$DATE.tar.gz /tmp/

# Restore database
echo "🗄️ Restoring database..."
gunzip < /tmp/db_$DATE.sql.gz | psql $DATABASE_URL

# Restore Redis
echo "⚡ Restoring Redis..."
redis-cli --rdb /tmp/redis_$DATE.rdb

# Restore files
echo "📁 Restoring files..."
tar -xzf /tmp/files_$DATE.tar.gz -C /

echo "✅ Restore completed!"
```

### Disaster Recovery Plan

```mermaid
graph TD
    A[אירוע אסון] --> B{סוג האירוע}
    B -->|נפילת שירות| C[Failover אוטומטי]
    B -->|אובדן נתונים| D[שחזור מגיבוי]
    B -->|תקיפת סייבר| E[Incident Response]
    
    C --> F[בדיקת Health]
    C --> G[הפעלת Standby]
    
    D --> H[זיהוי גיבוי אחרון]
    D --> I[שחזור DB]
    D --> J[אימות נתונים]
    
    E --> K[בידוד מערכת]
    E --> L[ניתוח forensics]
    E --> M[שחזור נקי]
    
    style A fill:#ff6b6b
    style F fill:#51cf66
    style G fill:#51cf66
    style J fill:#51cf66
    style M fill:#51cf66
```

## תחזוקה שוטפת 🔧

### Daily Tasks

```bash
#!/bin/bash
# scripts/daily_maintenance.sh

echo "🔍 Running daily maintenance..."

# 1. Check disk space
df -h | grep -E '^/dev/' | awk '{if($5+0 > 80) print "⚠️ Warning: "$1" is "$5" full"}'

# 2. Clean old logs
find /var/log -name "*.log" -mtime +30 -delete

# 3. Vacuum database
psql $DATABASE_URL -c "VACUUM ANALYZE;"

# 4. Clear expired cache
redis-cli --scan --pattern "cache:*" | xargs redis-cli DEL

# 5. Check SSL certificates
openssl x509 -enddate -noout -in /etc/ssl/cert.pem

# 6. Test backups
./scripts/test_backup.sh

echo "✅ Daily maintenance completed!"
```

### Weekly Tasks

```python
# scripts/weekly_maintenance.py
import asyncio
from datetime import datetime, timedelta

async def weekly_maintenance():
    """Run weekly maintenance tasks."""
    
    # 1. Generate reports
    await generate_weekly_report()
    
    # 2. Clean old reports
    cutoff = datetime.now() - timedelta(days=90)
    await archive_old_reports(cutoff)
    
    # 3. Update organization stats
    await recalculate_org_statistics()
    
    # 4. Security audit
    await run_security_scan()
    
    # 5. Performance analysis
    await analyze_slow_queries()
    
    print("✅ Weekly maintenance completed!")

if __name__ == "__main__":
    asyncio.run(weekly_maintenance())
```

## Performance Tuning ⚡

### Database Optimization

```sql
-- Analyze query performance
EXPLAIN (ANALYZE, BUFFERS) 
SELECT * FROM reports 
WHERE status = 'open' 
  AND created_at > NOW() - INTERVAL '7 days';

-- Create missing indexes
CREATE INDEX CONCURRENTLY idx_reports_created_status 
ON reports(created_at DESC, status) 
WHERE status IN ('open', 'in_progress');

-- Partition large tables
CREATE TABLE reports_2025_q1 PARTITION OF reports
FOR VALUES FROM ('2025-01-01') TO ('2025-04-01');

-- Update statistics
ANALYZE reports;
```

### Redis Optimization

```redis
# Check memory usage
INFO memory

# Set max memory policy
CONFIG SET maxmemory 2gb
CONFIG SET maxmemory-policy allkeys-lru

# Enable persistence
CONFIG SET save "900 1 300 10 60 10000"
CONFIG SET appendonly yes

# Monitor slow commands
CONFIG SET slowlog-log-slower-than 10000
SLOWLOG GET 10
```

### Application Optimization

```python
# Connection pooling
from sqlalchemy.pool import NullPool, QueuePool

engine = create_async_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=20,
    max_overflow=40,
    pool_timeout=30,
    pool_pre_ping=True
)

# Async batching
async def batch_process_reports(report_ids: List[str]):
    """Process reports in batches."""
    batch_size = 100
    
    for i in range(0, len(report_ids), batch_size):
        batch = report_ids[i:i + batch_size]
        await asyncio.gather(*[
            process_report(report_id) 
            for report_id in batch
        ])
```

## Health Checks 🏥

### Comprehensive Health Check

```python
# app/api/health.py
from typing import Dict, Any
import aiohttp
import asyncpg
import redis.asyncio as redis

@app.get("/health/detailed")
async def detailed_health_check() -> Dict[str, Any]:
    """Comprehensive health check."""
    
    health = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": APP_VERSION,
        "checks": {}
    }
    
    # Database check
    try:
        async with db_session() as session:
            await session.execute("SELECT 1")
        health["checks"]["database"] = {
            "status": "healthy",
            "response_time_ms": 5
        }
    except Exception as e:
        health["checks"]["database"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health["status"] = "degraded"
    
    # Redis check
    try:
        r = redis.from_url(REDIS_URL)
        await r.ping()
        health["checks"]["redis"] = {
            "status": "healthy",
            "response_time_ms": 2
        }
    except Exception as e:
        health["checks"]["redis"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health["status"] = "degraded"
    
    # External services
    for service, url in {
        "telegram": f"https://api.telegram.org/bot{BOT_TOKEN}/getMe",
        "google": "https://maps.googleapis.com/maps/api/geocode/json?address=test"
    }.items():
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as response:
                    if response.status == 200:
                        health["checks"][service] = {"status": "healthy"}
                    else:
                        health["checks"][service] = {
                            "status": "unhealthy",
                            "http_status": response.status
                        }
        except Exception as e:
            health["checks"][service] = {
                "status": "unhealthy",
                "error": str(e)
            }
    
    return health
```

## Troubleshooting Guide 🔍

### Common Issues

#### 1. High Memory Usage

```bash
# Check memory usage
ps aux | grep python | awk '{sum+=$6} END {print "Total RSS: " sum/1024 " MB"}'

# Find memory leaks
python -m tracemalloc app.main

# Solution: Restart workers
supervisorctl restart workers:*
```

#### 2. Slow Queries

```sql
-- Find slow queries
SELECT query, mean_exec_time, calls 
FROM pg_stat_statements 
ORDER BY mean_exec_time DESC 
LIMIT 10;

-- Kill long-running queries
SELECT pg_terminate_backend(pid) 
FROM pg_stat_activity 
WHERE state = 'active' 
  AND query_start < NOW() - INTERVAL '5 minutes';
```

#### 3. Redis Connection Pool Exhausted

```python
# Increase pool size
REDIS_MAX_CONNECTIONS = 200

# Monitor connections
redis-cli CLIENT LIST | wc -l

# Clear idle connections
redis-cli CLIENT KILL TYPE normal
```

## Security Hardening 🔒

### SSL/TLS Configuration

```nginx
# Strong SSL configuration
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES128-GCM-SHA256;
ssl_prefer_server_ciphers off;
ssl_session_timeout 1d;
ssl_session_cache shared:SSL:10m;
ssl_session_tickets off;
ssl_stapling on;
ssl_stapling_verify on;
add_header Strict-Transport-Security "max-age=63072000" always;
```

### Security Headers

```python
# app/core/security.py
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response
```

## Runbook למצבי חירום 🚨

### מצב 1: השירות לא מגיב

```bash
# 1. בדיקה ראשונית
curl -I https://animal-rescue.com/health

# 2. בדיקת שירותים
systemctl status animal-rescue-api
docker ps

# 3. בדיקת לוגים
tail -f /var/log/animal-rescue/error.log
journalctl -u animal-rescue-api -n 100

# 4. הפעלה מחדש
systemctl restart animal-rescue-api

# 5. אם לא עוזר - rollback
./scripts/rollback.sh
```

### מצב 2: מתקפת DDoS

```bash
# 1. הפעלת Cloudflare protection
curl -X PATCH "https://api.cloudflare.com/client/v4/zones/{zone_id}/settings/security_level" \
     -H "X-Auth-Email: admin@animal-rescue.com" \
     -H "X-Auth-Key: {api_key}" \
     -H "Content-Type: application/json" \
     --data '{"value":"under_attack"}'

# 2. Rate limiting
iptables -A INPUT -p tcp --dport 443 -m limit --limit 100/minute --limit-burst 200 -j ACCEPT

# 3. Block suspicious IPs
fail2ban-client set animal-rescue banip {ip_address}
```

### מצב 3: אובדן נתונים

```bash
# 1. עצירת כתיבות
redis-cli CONFIG SET stop-writes-on-bgsave-error yes

# 2. בדיקת extent של הנזק
psql $DATABASE_URL -c "SELECT COUNT(*) FROM reports WHERE created_at > NOW() - INTERVAL '1 hour';"

# 3. שחזור מגיבוי
./scripts/restore.sh $(date -d yesterday +%Y%m%d)

# 4. אימות
./scripts/verify_data_integrity.sh
```

## Checklist לפני Production

- [ ] **אבטחה**
  - [ ] HTTPS מופעל
  - [ ] סיסמאות חזקות
  - [ ] 2FA למנהלים
  - [ ] Rate limiting
  - [ ] CORS configured

- [ ] **ביצועים**
  - [ ] Database indexes
  - [ ] Redis caching
  - [ ] CDN לקבצים סטטיים
  - [ ] Compression enabled

- [ ] **ניטור**
  - [ ] Health checks
  - [ ] Metrics collection
  - [ ] Log aggregation
  - [ ] Alerts configured

- [ ] **גיבויים**
  - [ ] Automated backups
  - [ ] Tested restore
  - [ ] Off-site storage

- [ ] **תיעוד**
  - [ ] API documentation
  - [ ] Runbooks
  - [ ] Contact list
  - [ ] Architecture diagram

---

<div align="center">
  <strong>🎯 מוכנים לפרודקשן? בהצלחה!</strong>
</div>