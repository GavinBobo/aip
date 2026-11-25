<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

This is the All-Ontology web UI: a [Next.js](https://nextjs.org) App Router app that also
acts as the BFF. Every `/api/**` request is authorized in `app/api/**` and proxied to the
FastAPI backend, so **the backend on port 3001 must be running**. See the
**[root README](../README.md)** for full setup.

## Getting Started

The supported one-command start is the repo-root script, which brings up Postgres, the
backend, the ingestion worker and this frontend in order:

```powershell
.\dev_tools\start-dev.ps1
```

It opens the frontend on **http://localhost:3010** and the backend on
**http://localhost:3001**. Running `pnpm dev` in this directory starts only Next.js (also
on 3010) and assumes the backend is already up.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!
