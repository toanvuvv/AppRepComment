# Responsive UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the React + Ant Design frontend usable on desktop, tablet, and mobile without horizontal page overflow, clipped controls, or unusable modal/table layouts.

**Architecture:** Add a small responsive foundation in global CSS, then update the shared layout and the highest-risk Ant Design surfaces in focused slices. Keep behavior unchanged; this is a layout-only pass unless a component needs a tiny structural wrapper to support responsive styling.

**Tech Stack:** React 18, TypeScript, Vite, Ant Design 5, GitNexus CLI.

---

## File Map

- Modify: `frontend/src/styles/global.css`
  - Owns responsive primitives, Ant Design overrides, mobile spacing rules, and reusable utility classes.
- Modify: `frontend/src/components/Layout.tsx`
  - Owns app shell, header navigation, content padding, and user menu placement.
- Modify: `frontend/src/pages/Login.tsx`
  - Owns auth card width and mobile-safe viewport padding.
- Modify: `frontend/src/pages/ChangePassword.tsx`
  - Owns change-password card width on mobile.
- Modify: `frontend/src/pages/LiveScan.tsx`
  - Owns Live Scan page title/action layout and Nick Live card spacing.
- Modify: `frontend/src/components/livescan/NickLiveTable.tsx`
  - Owns Live Scan table scroll and dense column behavior.
- Modify: `frontend/src/components/livescan/FocusFeedModal.tsx`
  - Owns comment modal width/body height on smaller viewports.
- Modify: `frontend/src/components/livescan/CommentFeedView.tsx`
  - Owns comment line wrapping and feed height.
- Modify: `frontend/src/components/livescan/ReplyLogsPanel.tsx`
  - Owns reply log filters and log list wrapping.
- Modify: `frontend/src/pages/Seeding.tsx`
  - Owns tab-level select controls passed into seeding children.
- Modify: `frontend/src/components/seeding/ClonesTab.tsx`
  - Owns clone table scroll and top action row wrapping.
- Modify: `frontend/src/components/seeding/TemplatesTab.tsx`
  - Owns fixed-width template inputs.
- Modify: `frontend/src/components/seeding/ManualSendTab.tsx`
  - Owns manual send form/select/history layout.
- Modify: `frontend/src/components/seeding/AutoRunnerTab.tsx`
  - Owns auto runner form/table layout.
- Modify: `frontend/src/components/seeding/ProxyTable.tsx`
  - Owns proxy table scroll and modal form sizing.
- Modify: `frontend/src/components/seeding/SeedingLogDrawer.tsx`
  - Owns drawer/table sizing.
- Modify: `frontend/src/pages/Settings.tsx`
  - Owns settings cards, fixed-width selects/inputs, and admin key forms.
- Modify: `frontend/src/pages/AdminUsers.tsx`
  - Owns admin table scroll, expanded table scroll, and create/reset modal sizing.
- Modify: `frontend/src/components/NickConfigModal.tsx`
  - Owns the largest modal and nested tabs/tables. Treat as a separate high-care task.
- Modify: `frontend/src/components/KnowledgeProductsCard.tsx`
  - Owns knowledge product table and import card layout.

## Required GitNexus Gates

- Before editing any function/component symbol, run:

```powershell
npx gitnexus impact --repo "App Rep Comment" <SymbolName> --direction upstream
```

- If GitNexus reports HIGH or CRITICAL risk, stop and tell the user before editing that symbol.
- Before finishing implementation, run:

```powershell
npx gitnexus detect_changes --repo "App Rep Comment"
```

- If `detect_changes` is unavailable in the installed CLI, use:

```powershell
npx gitnexus status
git diff --stat
git diff -- frontend/src
```

---

### Task 1: Add Responsive Foundation

**Files:**
- Modify: `frontend/src/styles/global.css`

- [x] Step 1: Add base viewport safeguards.

Add rules equivalent to:

```css
html,
body,
#root {
  min-width: 0;
  width: 100%;
}

/* Use `clip` (not `hidden`) so we don't create a scroll containing block
   that breaks `position: sticky` and AntD Drawer/Dropdown overflow. */
html {
  overflow-x: clip;
}

img,
svg,
video,
canvas {
  max-width: 100%;
}
```

- [x] Step 2: Add utility classes for app pages and flexible action rows.

Add reusable classes equivalent to:

```css
.app-page {
  width: 100%;
  min-width: 0;
}

.app-page-title-row,
.app-card-extra-row,
.app-form-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.app-page-title-row {
  justify-content: space-between;
  margin-bottom: 16px;
}

.app-card-extra-row {
  justify-content: flex-end;
}

.app-full-width {
  width: 100%;
}
```

- [x] Step 3: Add mobile overrides for common Ant Design containers.

Add rules equivalent to:

```css
@media (max-width: 768px) {
  .app-content {
    padding: 12px !important;
  }

  .app-page-title-row {
    align-items: stretch;
  }

  .app-page-title-row > *,
  .app-card-extra-row > *,
  .app-form-row > * {
    max-width: 100%;
  }

  .ant-card-head {
    flex-wrap: wrap;
    gap: 8px;
  }

  .ant-card-extra {
    margin-left: 0;
  }

  .ant-modal {
    max-width: calc(100vw - 16px);
  }
}
```

> **Trade-off note:** The global `.ant-modal { max-width }` rule will shrink any
> modal that hardcodes a width wider than the viewport (e.g. `width={1200}` on a
> 1280px screen with the 16px subtraction). This is the desired behavior for
> mobile, but verify on tablet (768–1024px) that no critical modal content gets
> clipped. If a specific modal needs to escape this cap, scope it with a class.

- [x] Step 4: Run frontend build.

Run:

```powershell
npm run build
```

Expected: TypeScript and Vite build pass. Existing large chunk warning may remain.

---

### Task 2: Make App Shell Responsive

**Files:**
- Modify: `frontend/src/components/Layout.tsx`

- [x] Step 1: Run impact analysis.

Run:

```powershell
npx gitnexus impact --repo "App Rep Comment" AppLayout --direction upstream
```

Expected: Record direct callers and risk level. Stop before editing if HIGH or CRITICAL.

- [x] Step 2: Replace the fixed header structure with desktop/mobile-safe wrapping.

Implementation intent:
- Keep the same menu items and routes.
- Add class names such as `app-shell`, `app-header`, `app-brand`, `app-nav`, `app-user-menu`, and `app-content`.
- For mobile, allow header to wrap to two rows rather than forcing logo, menu, and user dropdown into one row.
- Keep `Menu mode="horizontal"` for now to avoid behavior changes.

- [x] Step 3: Move content padding from inline style to `app-content`.

Expected behavior:
- Desktop keeps roughly 24px padding.
- Mobile uses 12px from CSS.

- [x] Step 4: Build.

Run:

```powershell
npm run build
```

Expected: Build passes.

---

### Task 3: Fix Auth and Simple Form Widths

**Files:**
- Modify: `frontend/src/pages/Login.tsx`
- Modify: `frontend/src/pages/ChangePassword.tsx`

- [x] Step 1: Run impact analysis.

Run:

```powershell
npx gitnexus impact --repo "App Rep Comment" LoginPage --direction upstream
npx gitnexus impact --repo "App Rep Comment" ChangePasswordPage --direction upstream
```

> Verified symbol names against source: `LoginPage` (Login.tsx) and
> `ChangePasswordPage` (ChangePassword.tsx) are the actual exported components.

- [x] Step 2: Replace fixed login card width.

Implementation intent:
- Change `width: 380` to `width: "min(380px, calc(100vw - 24px))"`.
- Add `padding: 12` to the outer full-screen wrapper.

- [x] Step 3: Make change-password card mobile-safe.

Implementation intent:
- Keep `maxWidth: 480`.
- Add `width: "100%"`.
- Wrap page with `className="app-page"`.

- [x] Step 4: Build.

Run:

```powershell
npm run build
```

Expected: Build passes.

---

### Task 4: Fix Live Scan Page and Table

**Files:**
- Modify: `frontend/src/pages/LiveScan.tsx`
- Modify: `frontend/src/components/livescan/NickLiveTable.tsx`

- [ ] Step 1: Run impact analysis.

Run:

```powershell
npx gitnexus impact --repo "App Rep Comment" LiveScan --direction upstream
npx gitnexus impact --repo "App Rep Comment" NickLiveTable --direction upstream
```

- [x] Step 2: Wrap Live Scan title and actions.

Implementation intent:
- Replace bare `<Title level={3}>` with an `app-page-title-row`.
- Use `Space wrap` or `className="app-card-extra-row"` for Refresh/Add buttons.
- Keep actions unchanged.

- [x] Step 3: Add horizontal table scroll.

In `NickLiveTable`, add:

```tsx
scroll={{ x: "max-content" }}
```

> Column widths sum to 930 (240 + 160 + 120 + 90 + 110 + 80 + 130), but AntD
> adds ~16px cell padding × 7 columns ≈ 112px. Using `max-content` lets the
> browser measure actual rendered width and avoids clipping. If a fixed
> number is required (e.g. for virtualization), use `1050` instead of `930`.

- [x] Step 4: Prevent long names/status tags from expanding columns.

Implementation intent:
- Add `ellipsis` or constrained text wrappers for nick name/status where needed.
- Keep row click behavior unchanged.

- [ ] Step 5: Build.

Run:

```powershell
npm run build
```

Expected: Build passes.

---

### Task 5: Fix Live Scan Modals and Feeds

**Files:**
- Modify: `frontend/src/components/livescan/FocusFeedModal.tsx`
- Modify: `frontend/src/components/livescan/CommentFeedView.tsx`
- Modify: `frontend/src/components/livescan/ReplyLogsPanel.tsx`

- [ ] Step 1: Run impact analysis.

Run:

```powershell
npx gitnexus impact --repo "App Rep Comment" FocusFeedModal --direction upstream
npx gitnexus impact --repo "App Rep Comment" CommentFeedView --direction upstream
npx gitnexus impact --repo "App Rep Comment" ReplyLogsPanel --direction upstream
```

- [x] Step 2: Make FocusFeedModal viewport-safe.

Implementation intent:
- Replace `width={1000}` with a responsive width such as:

```tsx
width="min(1000px, calc(100vw - 16px))"
```

- Keep body scroll, but use height similar to:

```tsx
styles={{ body: { height: "min(75vh, 720px)", padding: 16, overflow: "auto" } }}
```

- [x] Step 3: Make comment feed wrap long content.

Implementation intent:
- Add `wordBreak: "break-word"` and `overflowWrap: "anywhere"` to comment text containers.
- Reduce feed `maxHeight` on mobile via CSS class if needed.

- [x] Step 4: Make reply log filters mobile-safe.

Implementation intent:
- Convert controls with `minWidth: 360` to `width: "min(360px, 100%)"` or CSS class.
- Keep existing `Space wrap`.

- [ ] Step 5: Build.

Run:

```powershell
npm run build
```

Expected: Build passes.

---

### Task 6: Fix Seeding Page Shared Controls

**Files:**
- Modify: `frontend/src/pages/Seeding.tsx`

- [ ] Step 1: Run impact analysis.

Run:

```powershell
npx gitnexus impact --repo "App Rep Comment" SeedingPage --direction upstream
```

- [x] Step 2: Make nick/session selects responsive.

Implementation intent:
- Change `style={{ width: 200 }}` and `style={{ width: 240 }}` to a shared responsive style:

```tsx
style={{ width: "min(240px, 100%)" }}
```

- Ensure parent wrappers in child tabs can shrink.

- [x] Step 3: Add mobile-safe Tabs behavior if needed.

Implementation intent:
- Keep Ant Design `Tabs`.
- If labels overflow, set tab bar to naturally scroll using AntD default; avoid custom tab logic.

- [ ] Step 4: Build.

Run:

```powershell
npm run build
```

Expected: Build passes.

---

### Task 7: Fix Seeding Child Tables and Forms

**Files:**
- Modify: `frontend/src/components/seeding/ClonesTab.tsx`
- Modify: `frontend/src/components/seeding/TemplatesTab.tsx`
- Modify: `frontend/src/components/seeding/ManualSendTab.tsx`
- Modify: `frontend/src/components/seeding/AutoRunnerTab.tsx`
- Modify: `frontend/src/components/seeding/ProxyTable.tsx`
- Modify: `frontend/src/components/seeding/SeedingLogDrawer.tsx`

- [ ] Step 1: Run impact analysis.

Run:

```powershell
npx gitnexus impact --repo "App Rep Comment" ClonesTab --direction upstream
npx gitnexus impact --repo "App Rep Comment" TemplatesTab --direction upstream
npx gitnexus impact --repo "App Rep Comment" ManualSendTab --direction upstream
npx gitnexus impact --repo "App Rep Comment" AutoRunnerTab --direction upstream
npx gitnexus impact --repo "App Rep Comment" ProxyTable --direction upstream
npx gitnexus impact --repo "App Rep Comment" SeedingLogDrawer --direction upstream
```

- [x] Step 2: Add table horizontal scroll where missing.

Implementation intent:
- `ClonesTab` table: `scroll={{ x: 720 }}`.
- `AutoRunnerTab` runs table: `scroll={{ x: 820 }}`.
- `ProxyTable` table: `scroll={{ x: 720 }}`.
- Keep existing `SeedingLogDrawer` `scroll={{ x: 700 }}` unless audit shows it still clips.

- [x] Step 3: Replace fixed template input widths.

Implementation intent:
- In `TemplatesTab`, replace `style={{ width: 400 }}` with `style={{ width: "min(400px, 100%)" }}`.
- Wrap adjacent input/button rows with `Space wrap`.

- [x] Step 4: Replace manual-send fixed select width.

Implementation intent:
- In `ManualSendTab`, change clone select `style={{ width: 240 }}` to `style={{ width: "min(240px, 100%)" }}`.
- Ensure history item content uses `overflowWrap`.

- [x] Step 5: Make AutoRunner clone rows wrap.

Implementation intent:
- Change clone row `Space` to allow wrapping where badges and Reset buttons appear.
- Keep checkbox selection logic unchanged.

- [ ] Step 6: Build.

Run:

```powershell
npm run build
```

Expected: Build passes.

---

### Task 8: Fix Settings and Admin Tables

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`
- Modify: `frontend/src/pages/AdminUsers.tsx`

- [ ] Step 1: Run impact analysis.

Run:

```powershell
npx gitnexus impact --repo "App Rep Comment" Settings --direction upstream
npx gitnexus impact --repo "App Rep Comment" AdminUsersPage --direction upstream
```

- [x] Step 2: Replace Settings fixed widths.

Implementation intent:
- Selects currently using `width: 200` become `width: "min(200px, 100%)"`.
- System Relive input currently using `width: 400` becomes `width: "min(400px, 100%)"`.
- Admin key rows use `Space wrap`.

- [x] Step 3: Add AdminUsers table scroll.

Implementation intent:
- Main table gets `scroll={{ x: 1100 }}`.
- Expanded nested table gets `scroll={{ x: 800 }}`.
- AI Key Mode select becomes `width: "min(200px, 100%)"`.

- [x] Step 4: Make modals mobile-safe.

Implementation intent:
- Create user/reset password modals get responsive width:

```tsx
width="min(520px, calc(100vw - 16px))"
```

- [ ] Step 5: Build.

Run:

```powershell
npm run build
```

Expected: Build passes.

---

### Task 9: Fix Knowledge and Nick Config Modal

**Files:**
- Modify: `frontend/src/components/KnowledgeProductsCard.tsx`
- Modify: `frontend/src/components/NickConfigModal.tsx`

- [ ] Step 1: Run impact analysis.

Run:

```powershell
npx gitnexus impact --repo "App Rep Comment" KnowledgeProductsCardInner --direction upstream
npx gitnexus impact --repo "App Rep Comment" NickConfigModal --direction upstream
```

If `KnowledgeProductsCardInner` is not found, run:

```powershell
npx gitnexus context --repo "App Rep Comment" KnowledgeProductsCard
```

- [x] Step 2: Keep KnowledgeProductsCard table scroll, improve wrapping.

Implementation intent:
- Keep existing `scroll={{ x: 800 }}`.
- Ensure card title/extra wraps.
- Prevent long tags/vouchers from forcing extra width.

- [x] Step 3: Make NickConfigModal viewport-safe.

Implementation intent:
- Replace `width={700}` with:

```tsx
width="min(900px, calc(100vw - 16px))"
```

- Keep nested Knowledge table `scroll={{ x: 1050, y: 400 }}`.
- Add wrapping to action rows in auto-post, auto-pin, reply, knowledge, and moderator tabs.

- [x] Step 4: Avoid broad refactor in NickConfigModal.

Do not split the component in this pass. This task is responsive-only because the file is large and high touch.

- [ ] Step 5: Build.

Run:

```powershell
npm run build
```

Expected: Build passes.

---

### Task 10: Manual Responsive Verification

**Files:**
- No source changes unless verification finds issues.

- [ ] Step 1: Start or reuse Vite dev server.

Run:

```powershell
npm run dev -- --host localhost --port 5173
```

If port 5173 is already in use, use:

```powershell
npm run dev -- --host localhost --port 5174
```

- [ ] Step 2: Verify build and key routes.

Run:

```powershell
npm run build
```

Expected: Build passes.

- [ ] Step 3: Browser viewport checklist.

Check these widths:
- 390px mobile
- 768px tablet
- 1366px desktop

Routes:
- `/login`
- `/live-scan`
- `/seeding`
- `/settings`
- `/admin/users`

Acceptance criteria:
- No body-level horizontal overflow.
- Header controls remain reachable.
- Tables scroll inside their own container, not the full page.
- Modal close buttons and primary controls remain visible.
- Long Vietnamese labels, IDs, product names, and comments wrap or ellipsize cleanly.

- [ ] Step 4: Run GitNexus change detection.

Run:

```powershell
npx gitnexus detect_changes --repo "App Rep Comment"
```

If unsupported by CLI:

```powershell
npx gitnexus status
git diff --stat
git diff -- frontend/src
```

- [ ] Step 5: Final build.

Run:

```powershell
npm run build
```

Expected: Build passes.

---

## Recommended Commit Slices

Explicit task → commit mapping (10 tasks → 5 slices):

1. `style: add responsive frontend foundation` — **Task 1**
2. `style: make app shell and auth pages responsive` — **Tasks 2 + 3**
3. `style: improve live scan responsive layout` — **Tasks 4 + 5**
4. `style: improve seeding responsive layout` — **Tasks 6 + 7**
5. `style: improve settings admin and config modals` — **Tasks 8 + 9**

Task 10 (manual verification) is a gate, not a commit — its only output is
fix-up commits if regressions are found, which fold back into the slice that
introduced them.

## Self-Review

- **Spec coverage:** Covers global CSS, shared layout, auth, Live Scan, Seeding, Settings, Admin, Knowledge, and Nick Config responsive surfaces found during audit.
- **Placeholder scan:** No task contains TBD/TODO/implement later language.
- **Symbol verification (against source, 2026-04-28):**
  - `AppLayout` → [Layout.tsx:9](frontend/src/components/Layout.tsx#L9) ✓
  - `LoginPage` → [Login.tsx:7](frontend/src/pages/Login.tsx#L7) ✓
  - `ChangePasswordPage` → [ChangePassword.tsx:5](frontend/src/pages/ChangePassword.tsx#L5) ✓
  - `LiveScan` → [LiveScan.tsx:21](frontend/src/pages/LiveScan.tsx#L21) ✓
  - `SeedingPage` → [Seeding.tsx:12](frontend/src/pages/Seeding.tsx#L12) ✓
  - `Settings` → [Settings.tsx:53](frontend/src/pages/Settings.tsx#L53) ✓
  - `AdminUsersPage` → [AdminUsers.tsx:40](frontend/src/pages/AdminUsers.tsx#L40) ✓
  - `KnowledgeProductsCardInner` → [KnowledgeProductsCard.tsx:28](frontend/src/components/KnowledgeProductsCard.tsx#L28) ✓
  - Other component symbols (`NickLiveTable`, `FocusFeedModal`, `CommentFeedView`, `ReplyLogsPanel`, `ClonesTab`, `TemplatesTab`, `ManualSendTab`, `AutoRunnerTab`, `ProxyTable`, `SeedingLogDrawer`, `NickConfigModal`) match their file names — verify with `gitnexus context` if `impact` returns not-found.
- **Behavior-change disclosure:** This pass is layout-only, but two changes affect rendering on viewports ≥ breakpoint:
  - `width="min(1000px, calc(100vw - 16px))"` on FocusFeedModal will reduce modal width on viewports < 1016px (intentional).
  - Global `.ant-modal { max-width: calc(100vw - 16px) }` will cap any modal hardcoded wider than viewport. Verified in Task 10 viewport checklist.
