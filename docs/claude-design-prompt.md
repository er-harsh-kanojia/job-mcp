# Design brief: "Job MCP", a local dashboard for job search and bulk applying

## Goal and audience
Design a clickable, high-fidelity prototype for **Job MCP**, a personal web app that runs locally. It has one user: an AI/ML engineer in India with 4 years of experience. The app reuses saved browser sessions to log into job portals, searches several of them at once, ranks jobs against the user's profile, and bulk-applies, with a dry-run mode for testing. It also runs as an MCP server for Claude, so this UI is the visual control room for those same actions.

Platforms: **Naukri, Instahyre, Indeed** (live). **LinkedIn, Wellfound, Hirist** are planned and should be shown as "Coming soon".

The user is technical and opens the app daily. Optimise for scanning speed, trust (always being clear about what the app did or will do) and control. Skip marketing polish.

## Visual direction
- A dense but calm productivity dashboard at the level of Linear or Vercel. Use a neutral base with one accent colour, thin borders and minimal shadow.
- Light and dark themes, both first-class.
- Each platform gets its own accessible colour, used as a badge or dot, never as a large fill. Always pair the colour with a label.
- Clear type hierarchy, with tabular numerals for scores, counts and salaries.
- Desktop-first (1440px) and responsive. Tables become cards on mobile.
- Keyboard-friendly: Ctrl+K command palette, J/K to move through rows, X to select, Enter to open, / to focus search. Show the shortcut hints and use visible focus rings.

## App shell
Sidebar: Dashboard, Search, Applications, Platforms, Profile. The top bar holds session-health dots for each platform, a **Dry run / Live** mode chip that is always visible, and the theme toggle.

## Screens
1. **Dashboard:** cards for applied today, applied this week and success rate; a per-platform breakdown chart; a recent-activity feed; warnings about expired sessions; and a "Run search" shortcut.
2. **Search and Results**
   - Filters: keyword chips (defaults: AI/ML Engineer, ML Engineer, AI Engineer, Python AI Engineer, AI Cloud Engineer, GenAI Engineer, LLM Engineer, Deep Learning Engineer), location (default India), years of experience, a multi-select of platforms and a minimum match score slider (default 0.25).
   - A ranked table. Each row shows title, company, platform badge, location, salary in LPA or "Not disclosed", experience range, how long ago it was posted, an Easy Apply flag, and a **match score** shown as a small bar or ring plus a number. Show the rank score too.
   - Experience edge cases: an unknown range (-1) shows "Exp n/a", and 99 shows "5+ yrs".
   - Sorting, a density toggle, checkboxes and a sticky selection bar ("12 selected: Compare, Bulk apply"). Comparison puts 2 to 4 jobs side by side.
3. **Job detail drawer:** full metadata, a description snippet, skill chips that highlight the ones matching the profile, "Open on platform" and "Add to apply queue".
4. **Bulk Apply flow** (a stepper):
   - **Review:** the selected jobs, with any that will be skipped flagged up front (already applied, not Easy Apply). Include a max applications input (default 20) and the dry-run toggle.
   - **Confirm:** an explicit summary ("Apply to 18 jobs on Naukri and Instahyre").
   - **Live progress:** every job streams its status (queued, applying, applied, failed, skipped), alongside an overall progress bar and a Stop control.
   - **Results:** summary counts, then applied, failed (with the reason) and skipped lists. Include "Retry failed" and "View in tracker".
5. **Applications tracker:** a table with status filters (applied / failed / skipped / dry_run), platform filters, a date range (last 7 days, last 30 days or custom) and a grouping by platform.
6. **Platforms and Sessions:** a card for each platform showing Logged in, Expired or Not set up, plus when it was last checked and a **Login** button. The button opens a real browser window for manual login, so show a "Waiting for you to finish logging in…" state. Planned platforms appear as disabled cards.
7. **Profile and Autofill**
   - Sectioned forms with a sticky save bar:
     - **Personal:** name, email, phone, location, resume upload.
     - **Compensation and notice:** current and expected CTC (LPA), notice period.
     - **Education and cloud:** highest qualification, graduation year, primary cloud.
     - **Skills:** a compact grid with years of experience for Python, ML, DL, NLP, GenAI, LLM, LangChain, RAG, TensorFlow, PyTorch, scikit-learn, MLOps and CV.
     - **Preferred locations:** chips for Delhi NCR, Gurugram, Noida, Hyderabad, Jaipur, Remote, Pune, Bengaluru, Mumbai.
   - **There are no password fields.** Add a note that logins happen manually in the browser.

## States to design (show each one)
- **Empty:** first run with no sessions and no applications, guiding the user to set up platforms and then search.
- **Searching:** a progress row for each platform (Naukri done with 42 jobs, Instahyre fetching, Indeed queued) while skeleton rows stream in.
- **Soft failure:** Indeed blocked by a captcha while the other platforms succeed. Show an inline warning with "Retry Indeed" and keep the other results.
- **Session expired:** flagged on the platform card, in the top bar and in the search panel, with a direct Login action.
- **Dry run vs Live:** dry run looks calm and neutral, with a "Simulation" label. **Live mode must be unmistakable:** use a persistent warning-coloured banner, an "Apply for real" button label, and a deliberate confirmation such as typing APPLY. Dry-run rows in the tracker must also look clearly different.
- **Errors:** a backend that can't be reached, a single job failing to apply, and validation errors on profile fields.

## Sample data
Use realistic Indian data throughout:
- Companies such as Fractal Analytics, Sarvam AI, Swiggy, Razorpay, CRED, Meesho, PhonePe, Tredence, LatentView, TCS and Infosys.
- Salaries such as "18–28 LPA".
- Cities such as Bengaluru, Gurugram, Noida, Hyderabad and Pune, plus Remote.
- Recency such as "Today" or "3d ago".
- Match scores spread between 0.25 and 0.95.

## Deliverables
1. A **clickable prototype** covering every screen and the full bulk-apply flow, with a small state switcher so the states above can be reviewed.
2. A **component inventory**: a short list of reusable components (PlatformBadge, MatchScore, StatusPill, JobRow, FilterBar, SelectionBar, Stepper, ProgressRow, SessionCard, ModeBanner and so on) with their variants and states.
3. **Design tokens** for both themes: colour (neutrals, accent, the six platform colours, success/warning/danger/info, dry-run and live), type scale, spacing, radius, shadow and motion. Express them as CSS variables and a Tailwind theme extension, ready to build in **React + Tailwind**.

Start with Search and Results and the Bulk Apply flow, since they matter most. Then build the remaining screens on the same system.
