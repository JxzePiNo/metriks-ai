# Metriks AI — Frontend

Next.js (App Router) + React + TypeScript (strict) + Tailwind CSS web application for the Metriks AI document management system.

## Prerequisites

- Node.js 20.9 or newer (developed with Node 22)
- npm

## Setup

```bash
cd frontend
npm install
cp .env.example .env.local
```

## Environment variables

| Variable              | Description                      | Default                 |
| --------------------- | -------------------------------- | ----------------------- |
| `NEXT_PUBLIC_API_URL` | Base URL of the backend REST API | `http://localhost:8000` |

`NEXT_PUBLIC_*` variables are embedded in the browser bundle. Never put secrets in them. `.env.local` is git-ignored.

## Development

```bash
npm run dev
```

Open <http://localhost:3000>.

## Quality checks

```bash
npm run lint        # ESLint
npm run typecheck   # next typegen + tsc --noEmit
npm run build       # production build
npm run start       # serve the production build
```

## Structure

```
src/
  app/
    layout.tsx             root layout (fonts, metadata, skip link)
    (marketing)/           landing page with site header/footer
    (app)/dashboard/       dashboard shell with sidebar navigation
  components/              shared UI (Logo, NavLinks, MobileMenu, ...)
  lib/
    config.ts              reads and validates NEXT_PUBLIC_API_URL
    api/                   typed fetch client (apiFetch, ApiError) and contracts
```

## Current scope

This is the frontend foundation only. The dashboard is an empty-state shell; there is no authentication, document upload or backend call yet. The API client in `src/lib/api` is ready for use but is not called anywhere.
