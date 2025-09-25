# API Reference 📡

תיעוד מלא של ה-REST API למערכת בוט חילוץ בעלי חיים.

## Base URL

```
Production: https://api.animal-rescue.com
Staging: https://staging-api.animal-rescue.com
Local: http://localhost:8000
```

## Authentication

### API Key Authentication

```http
GET /api/v1/reports
Authorization: Bearer YOUR_API_KEY
```

### JWT Authentication

```http
POST /api/v1/auth/login
Content-Type: application/json

{
  "username": "user@example.com",
  "password": "your_password"
}
```

Response:
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

## Endpoints

### Reports 📋

#### Create Report
```http
POST /api/v1/reports/
```

Request Body:
```json
{
  "description": "כלב פצוע ברחוב הרצל",
  "lat": 32.0853,
  "lon": 34.7818,
  "urgency": "high",
  "animal_type": "dog",
  "images": ["base64_image_data"],
  "reporter_phone": "+972501234567"
}
```

Response:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "open",
  "created_at": "2025-01-15T10:30:00Z",
  "tracking_number": "REP-2025-0142"
}
```

Note:
- Primary notifications are sent to rescue organizations/shelters/volunteer groups/municipality only.
- The reporter receives guidance with a short checklist and up to 3 nearby veterinary clinics (name/address/phone) for self‑transport if possible.

#### Get Report
```http
GET /api/v1/reports/{report_id}
```

Response:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "description": "כלב פצוע ברחוב הרצל",
  "location": {
    "lat": 32.0853,
    "lon": 34.7818,
    "address": "רחוב הרצל 15, תל אביב"
  },
  "status": "in_progress",
  "urgency": "high",
  "animal_type": "dog",
  "assigned_organization": {
    "id": "org_123",
    "name": "עמותת צער בעלי חיים"
  },
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T10:45:00Z"
}
```

#### List Reports
```http
GET /api/v1/reports/
```

Query Parameters:
| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `status` | string | Filter by status (open/in_progress/closed) | all |
| `urgency` | string | Filter by urgency (low/medium/high) | all |
| `animal_type` | string | Filter by animal type | all |
| `lat` | float | Latitude for proximity search | - |
| `lon` | float | Longitude for proximity search | - |
| `radius` | float | Radius in km | 10 |
| `page` | int | Page number | 1 |
| `limit` | int | Items per page | 20 |

Response:
```json
{
  "items": [...],
  "total": 150,
  "page": 1,
  "pages": 8,
  "limit": 20
}
```

#### Update Report Status
```http
PATCH /api/v1/reports/{report_id}/status
```

Request Body:
```json
{
  "status": "closed",
  "resolution": "הכלב חולץ והועבר לטיפול וטרינרי"
}
```

### Organizations 🏢

#### List Organizations
```http
GET /api/v1/organizations/
```

Query Parameters:
| Parameter | Type | Description |
|-----------|------|-------------|
| `active` | bool | Filter active organizations |
| `lat` | float | Latitude for proximity search |
| `lon` | float | Longitude for proximity search |
| `radius` | float | Radius in km |

#### Get Organization
```http
GET /api/v1/organizations/{org_id}
```

Response:
```json
{
  "id": "org_123",
  "name": "עמותת צער בעלי חיים",
  "address": "רחוב הרצל 15, תל אביב",
  "phone": "+972-3-1234567",
  "email": "info@animals.org",
  "whatsapp": "+972501234567",
  "service_radius_km": 20,
  "languages": ["he", "en"],
  "active": true,
  "statistics": {
    "reports_handled": 450,
    "avg_response_time_minutes": 8.5,
    "success_rate": 0.92
  }
}
```

#### Register Organization
```http
POST /api/v1/organizations/register
```

Request Body:
```json
{
  "name": "מקלט חדש לחיות",
  "registration_number": "580123456",
  "address": "רחוב הגפן 10, חיפה",
  "contact": {
    "phone": "+972-4-8765432",
    "email": "contact@newshelter.org",
    "whatsapp": "+972509876543"
  },
  "service_area": {
    "lat": 32.8191,
    "lon": 34.9983,
    "radius_km": 15
  }
}
```

### Notifications 🔔

#### Send Test Notification
```http
POST /api/v1/notifications/test
```

Request Body:
```json
{
  "organization_id": "org_123",
  "channel": "whatsapp",
  "message": "בדיקת מערכת התראות"
}
```

#### Get Notification History
```http
GET /api/v1/notifications/history
```

Query Parameters:
| Parameter | Type | Description |
|-----------|------|-------------|
| `org_id` | string | Filter by organization |
| `report_id` | string | Filter by report |
| `status` | string | sent/delivered/failed |
| `from_date` | datetime | Start date |
| `to_date` | datetime | End date |

### Statistics 📊

#### Get System Statistics
```http
GET /api/v1/stats/system
```

Response:
```json
{
  "total_reports": 2543,
  "active_reports": 23,
  "total_organizations": 215,
  "active_organizations": 189,
  "avg_response_time_minutes": 4.7,
  "success_rate": 0.89,
  "reports_by_status": {
    "open": 23,
    "in_progress": 45,
    "closed": 2475
  },
  "reports_by_animal": {
    "dog": 1234,
    "cat": 987,
    "bird": 234,
    "other": 88
  }
}
```

#### Get Organization Statistics
```http
GET /api/v1/stats/organization/{org_id}
```

Query Parameters:
| Parameter | Type | Description |
|-----------|------|-------------|
| `period` | string | day/week/month/year |
| `from_date` | date | Start date |
| `to_date` | date | End date |

### Webhooks 🪝

#### Register Webhook
```http
POST /api/v1/webhooks/
```

Request Body:
```json
{
  "url": "https://your-service.com/webhook",
  "events": ["report.created", "report.assigned", "report.closed"],
  "secret": "your_webhook_secret",
  "active": true
}
```

#### Webhook Events

| Event | Description | Payload |
|-------|-------------|---------|
| `report.created` | New report created | Report object |
| `report.assigned` | Report assigned to organization | Report + Organization |
| `report.updated` | Report status changed | Report + Changes |
| `report.closed` | Report closed | Report + Resolution |
| `organization.joined` | New organization registered | Organization |

#### Webhook Payload Example
```json
{
  "event": "report.created",
  "timestamp": "2025-01-15T10:30:00Z",
  "data": {
    "report": {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "description": "כלב פצוע",
      "location": {...},
      "urgency": "high"
    }
  },
  "signature": "sha256=abcdef123456..."
}
```

### Health & Monitoring 🏥

#### Health Check
```http
GET /health
```

Response:
```json
{
  "status": "healthy",
  "version": "2.0.0",
  "services": {
    "database": "connected",
    "redis": "connected",
    "telegram": "connected",
    "google_api": "connected"
  },
  "timestamp": "2025-01-15T10:30:00Z"
}
```

#### Metrics (Prometheus Format)
```http
GET /metrics
```

Response:
```
# HELP http_requests_total Total HTTP requests
# TYPE http_requests_total counter
http_requests_total{method="GET",endpoint="/api/v1/reports",status="200"} 1234

# HELP active_reports Number of active reports
# TYPE active_reports gauge
active_reports{status="open"} 23
```

## Error Responses

### Error Format
```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Report not found",
    "details": {
      "report_id": "550e8400-e29b-41d4-a716-446655440000"
    },
    "timestamp": "2025-01-15T10:30:00Z",
    "request_id": "req_abc123"
  }
}
```

### Common Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `UNAUTHORIZED` | 401 | Missing or invalid authentication |
| `FORBIDDEN` | 403 | Insufficient permissions |
| `RESOURCE_NOT_FOUND` | 404 | Resource doesn't exist |
| `VALIDATION_ERROR` | 422 | Invalid request data |
| `RATE_LIMITED` | 429 | Too many requests |
| `INTERNAL_ERROR` | 500 | Server error |

## Rate Limiting

| Endpoint | Limit | Window |
|----------|-------|--------|
| Authentication | 5 requests | 1 minute |
| Report Creation | 10 requests | 1 minute |
| General API | 100 requests | 1 minute |
| Webhooks | 1000 requests | 1 hour |

Rate limit headers:
```http
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1642248000
```

## SDKs & Libraries

### Python
```python
from animal_rescue import Client

client = Client(api_key="YOUR_API_KEY")

# Create report
report = client.reports.create(
    description="כלב פצוע",
    lat=32.0853,
    lon=34.7818,
    urgency="high"
)

# Get organizations
orgs = client.organizations.list(
    lat=32.0853,
    lon=34.7818,
    radius=10
)
```

### JavaScript/TypeScript
```javascript
import { AnimalRescueClient } from '@animal-rescue/sdk';

const client = new AnimalRescueClient({
  apiKey: 'YOUR_API_KEY'
});

// Create report
const report = await client.reports.create({
  description: 'כלב פצוע',
  lat: 32.0853,
  lon: 34.7818,
  urgency: 'high'
});
```

### cURL Examples
```bash
# Get report
curl -X GET "https://api.animal-rescue.com/api/v1/reports/550e8400" \
     -H "Authorization: Bearer YOUR_API_KEY"

# Create report
curl -X POST "https://api.animal-rescue.com/api/v1/reports/" \
     -H "Authorization: Bearer YOUR_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{
       "description": "כלב פצוע",
       "lat": 32.0853,
       "lon": 34.7818,
       "urgency": "high"
     }'
```

## Postman Collection

[Download Postman Collection](https://api.animal-rescue.com/postman/collection.json)

## OpenAPI Specification

- **Swagger UI**: https://api.animal-rescue.com/docs
- **ReDoc**: https://api.animal-rescue.com/redoc
- **OpenAPI JSON**: https://api.animal-rescue.com/openapi.json

---

<div align="center">
  <strong>📧 לשאלות API: api@animal-rescue.com</strong>
</div>