# Stitch UI Brief For YouTube Transcriber

Use this brief with Stitch to generate production-ready UI concepts that match the current app updates.
Reference style direction: https://www.cloudflare.com/

## Product Context

- Product: YouTube Transcriber operations app
- Primary user: operator managing video transcription jobs
- Primary action: queue a single video URL
- Secondary action: import a channel for batch processing
- Tone: fast, reliable, operational clarity

## UX Constraints

- Keep one primary CTA per screen.
- Apply progressive disclosure for advanced actions.
- Make status and failure recovery visible without scrolling on desktop.
- Prioritize one-handed use on mobile.

## Visual Direction

- Typography:
- Headings: Manrope
- Body: Public Sans
- Surface style: clean white panels with firm borders and minimal depth
- Background: flat light neutral canvas (no gradients)
- Primary accent: Cloudflare-like orange
- Avoid purple-heavy palettes and decorative visual effects

## Component Rules

- Sidebar nav with clear active state and compact status block
- Hero panel with value proposition and trust/proof chips
- Metric cards (4-up desktop, 2-up mobile)
- Queue card with live status and retry controls
- Data table optimized for scanning: status, progress, created time, actions

## Accessibility Requirements

- Strong visible focus states
- Touch targets at least 44px on mobile
- Descriptive labels for inputs and actions
- Contrast ratio aligned with WCAG AA at minimum

## Prompt 1: Dashboard Refresh

Design a responsive operations dashboard for a YouTube transcription tool.
Primary action is "Start Transcription Job" from a single URL input.
Secondary action is "Import Channel" hidden under progressive disclosure.
Include:
1) hero section with trust chips
2) 4 metric cards
3) live queue panel with retry and cancel actions
4) recent jobs table
Use Manrope + Public Sans, flat surfaces with clear borders, orange accents, and clear status badges.
Optimize for fast scanning and low cognitive load.

## Prompt 2: Queue-First Mobile Screen

Create a mobile-first queue management screen for transcription jobs.
Top area: queue health, active count, and one dominant "Queue Video" button.
Middle: active and pending jobs with progress bars and concise status text.
Bottom: failed jobs grouped with inline retry.
Use thumb-friendly spacing, large tap targets, and obvious visual hierarchy.
No dark mode. No gradients. No purple-heavy palette.

## Prompt 3: Library + Search Workspace

Design a desktop-first library/search workspace.
Left: faceted filters (status, channel, date, transcript availability).
Main: searchable video list with row-level status and quick actions.
Right optional panel: selected video summary and job history.
Ensure keyboard navigation and sensible empty/loading/error states.
Match the same design language as dashboard: clean, operational, confidence-building.
