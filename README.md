# League OS Backend

Fan registration, email OTP verification, authentication, authorization, session management, and role-based access control API built with Django, Django REST Framework, PostgreSQL, JWT authentication, and drf-spectacular.

## Features

- Email-based fan registration with first/last name
- Secure 6-digit OTP generation and hashing
- Email verification with HTML and plain-text templates
- JWT authentication using SimpleJWT
- Rate-limited OTP resend
- Registration status endpoint
- Audit logging
- Login throttling and account locking
- Session management
- Login history tracking
- Role-based access control (RBAC)
- Generic permission engine
- OpenAPI schema with drf-spectacular

## Requirements

- Python 3.11+
- PostgreSQL 16
- SMTP credentials

## Setup

1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # on Windows: .venv\Scripts\activate
   pip install -r requirements/base.txt
   ```

2. Copy `.env.example` to `.env` and configure:
   ```env
   DJANGO_SECRET_KEY=change-me
   DJANGO_DEBUG=True
   DATABASE_URL=postgres://user:password@localhost:5432/leagueos
   EMAIL_HOST=smtp.gmail.com
   EMAIL_PORT=587
   EMAIL_USE_TLS=True
   EMAIL_HOST_USER=noreply@leagueos.com
   EMAIL_HOST_PASSWORD=app-password
   DEFAULT_FROM_EMAIL=noreply@leagueos.com
   CORS_ALLOWED_ORIGINS=http://localhost:5173
   CSRF_TRUSTED_ORIGINS=http://localhost:5173
   ```

3. Run migrations:
   ```bash
   python manage.py migrate
   ```

4. Seed initial system roles:
   ```bash
   python manage.py seed_roles
   ```

5. Start the server:
   ```bash
   python manage.py runserver
   ```

## API

Base URL: `http://localhost:8000/api/v1`

### Register

Create a fan account and send a verification OTP.

```bash
POST /api/v1/auth/register/
```

Request body:
```json
{
  "first_name": "Faith",
  "last_name": "Akiror",
  "email": "faith.akiror@gmail.com",
  "password": "StrongPass123!",
  "confirm_password": "StrongPass123!"
}
```

### Verify OTP

Verify the OTP sent to the fan email.

```bash
POST /api/v1/auth/verify-otp/
```

Request body:
```json
{
  "email": "faith.akiror@gmail.com",
  "otp": "123456"
}
```

### Resend OTP

Request a new OTP if the previous one expired.

```bash
POST /api/v1/auth/resend-otp/
```

Request body:
```json
{
  "email": "faith.akiror@gmail.com"
}
```

### Login

Obtain JWT tokens after email verification.

```bash
POST /api/v1/auth/login/
```

Request body:
```json
{
  "email": "faith.akiror@gmail.com",
  "password": "StrongPass123!"
}
```

### Logout

Blacklist refresh token and terminate session.

```bash
POST /api/v1/auth/logout/
```

Request body:
```json
{
  "refresh": "<refresh_token>"
}
```

### Logout All Devices

Terminate all active sessions.

```bash
POST /api/v1/auth/logout-all/
```

### Profile

Get the authenticated fan profile.

```bash
GET /api/v1/auth/profile/
Authorization: Bearer <access_token>
```

### Current User

Get current user profile.

```bash
GET /api/v1/auth/me/
Authorization: Bearer <access_token>
```

### Sessions

Get active sessions.

```bash
GET /api/v1/auth/sessions/
Authorization: Bearer <access_token>
```

### Registration Status

Check whether a fan is registered and verified.

```bash
GET /api/v1/auth/registration-status/?email=faith.akiror@gmail.com
```

## Development

Run tests:
```bash
python -m pytest accounts/tests/test_registration.py authentication/tests/test_authentication.py -v
```

Run tests with coverage:
```bash
python -m pytest --cov=accounts --cov=authentication --cov-report=term-missing --cov-report=xml
```

Format code:
```bash
black .
ruff format .
ruff check .
```

Seed roles:
```bash
python manage.py seed_roles
```

## Security

- OTPs are hashed before storage.
- OTPs expire after a configurable number of minutes.
- Account activation requires verified email.
- Rate limiting prevents brute-force verification attempts.
- Email is normalized to lowercase before storage.
- Login throttling locks accounts after repeated failures.
- Refresh token rotation and blacklisting supported.
- All timestamps are timezone-aware.