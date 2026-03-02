# GEI Tracking Bot - Web Simulator

A standalone web simulator for the GEI Tracking Bot mapping the exact Telegram flows to a fully functional React Next.js interface.

## Prerequisites
- Node.js 18+
- Supabase Project

## Local Setup

1. Install dependencies:
npm install

2. Configure environment variables in `.env.local`:
NEXT_PUBLIC_SUPABASE_URL=your_supabase_url
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_supabase_anon_key

3. Run development server:
npm run dev

Open [http://localhost:3000](http://localhost:3000) with your browser.

## Deployment (Vercel)

This application is ready to be deployed to Vercel:

1. Push your repository to GitHub/GitLab/Bitbucket.
2. Go to Vercel Dashboard -> Add New Project.
3. Import the repository.
4. Set the "Framework Preset" to `Next.js`.
5. Set the "Root Directory" to `simulator`.
6. Add Environment Variables (`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`).
7. Click "Deploy".
