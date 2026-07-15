# SmarterJobHunt — Frontend

React + Tailwind CSS frontend for the job-posting aggregator. This first pass covers
the **Landing page** and the **Job Listings dashboard**, wired up with sample data
so the UI is fully interactive before the real backend exists.

## Stack

- **Vite + React** — build tool and UI library
- **Tailwind CSS v4** — via the `@tailwindcss/vite` plugin, theme tokens live in
  `src/index.css` under `@theme`
- **React Router** — client-side routing (`/` = Landing, `/dashboard` = Job Listings)

## Getting started

```bash
npm install
npm run dev
```

Then open the printed local URL. `npm run build` produces a production build in `dist/`.

## Project structure

```
src/
  assets/logo.jpg          Product logo
  components/
    Navbar.jsx              Shared top nav
    Footer.jsx               Shared footer
    MatchRing.jsx            Circular match-% gauge (used on job cards)
    LoopVisual.jsx            Hero graphic on the landing page
    PillRadioGroup.jsx        Reusable pill-style radio control
    FilterSidebar.jsx         Job Listings sidebar: filters + saved searches
    JobCard.jsx                Single job listing card
  data/
    sampleJobs.js              Placeholder job data — swap for API calls later
  pages/
    Landing.jsx                 "/" — hero, search bar, video explainer, reviews
    JobListings.jsx              "/dashboard" — filters + listing cards
  App.jsx                        Route definitions
  main.jsx                        Entry point, wraps app in BrowserRouter
  index.css                       Tailwind import + design tokens (colors, fonts)
```

## Design tokens

Brand colors and fonts are defined once in `src/index.css` (`@theme` block) and
used throughout as Tailwind utilities: `bg-ember`, `text-ink-soft`, `font-display`,
etc. Change them there to restyle the whole app.

## Where the mock data lives

`src/data/sampleJobs.js` stands in for the real job listings until the SQL
database and scraping agent are wired up. `JobListings.jsx` already does real
client-side filtering (title, posted-within-days, funding stage) against that
array — swapping in a real API just means replacing that array with a fetch call.

## Not built yet (next steps)

- Backend / SQL database and API endpoints
- Wiring the AI scraping agent's output into the listings
- Auth (Create Account / Login currently just links to `/dashboard`)
- "See them all" (per-company listings) and saved-search persistence beyond
  the current session
