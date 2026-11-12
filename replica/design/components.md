# Corvi component specifications

## Navigation rail

Variants: home, projects, history, settings. Size: 68px wide.
States: default, hover, active, focus-visible, disabled.
Tokens: `surface`, `surface-hover`, `accent`, radius `md`.
A11y: real buttons with accessible labels; keyboard focus must be visible.
Used on: S01–S09.

## Workspace menu

Variants: current workspace, switch workspace, settings.
States: closed, open, keyboard-focused, unavailable.
Tokens: `surface-raised`, `border`, `text`, `shadow-pop`, radius `md`.
A11y: real disclosure button with `aria-expanded`; Escape closes it.
Used on: S01, S02, S05.

## Task row

Variants: recent, pinned, active.
States: default, hover, selected, unread, loading, missing workspace.
Tokens: `surface`, `surface-hover`, `text`, `text-muted`, radius `sm`.
A11y: selectable button/list item; selected state exposed to assistive technology.
Used on: S03, S04.

## Composer

Variants: empty, filled, multiline, council-enabled.
States: default, focused, sending, disabled, unavailable.
Tokens: `surface-raised`, `border-input`, `text`, `text-muted`, `action`, radius `lg`.
A11y: labelled textarea, Enter sends, Shift+Enter inserts a newline, send button has a label.
Used on: S01, S02.

## Status indicator

Variants: running, ready, needs-input, blocked, error.
States: animated, static, dismissed.
Tokens: success, warning, danger, text-muted.
A11y: status uses `aria-live="polite"`; animation respects reduced motion.
Used on: S02, S06, S10.

## Activity card

Variants: read, edit, command, browser, research.
States: collapsed, expanded, running, success, failure.
Tokens: `surface-raised`, `border`, `text`, `text-muted`, mono font.
A11y: expandable button with a descriptive summary; command output is selectable text.
Used on: S02, S06.

## Approval card

Variants: file edit, shell command, external action.
States: waiting, approved, denied, expired.
Tokens: warning, action, danger, `surface-raised`, radius `md`.
A11y: approval and denial are separate labelled buttons; dangerous action is explicit.
Used on: S07.

## Diff viewer

Variants: file diff, summary, conflict.
States: clean, changed, conflict, loading.
Tokens: success for additions, danger for deletions, mono font, `surface-raised`.
A11y: preserve line numbers and readable contrast; do not communicate changes by color alone.
Used on: S07, S08.

## Output/source row

Variants: file, source, report, terminal.
States: available, opened, missing, loading.
Tokens: `surface`, `surface-hover`, `accent`, `text-muted`.
A11y: use real buttons/links; icons have text labels or accessible names.
Used on: S08.

## Pet overlay

Variants: idle, thinking, coding, waiting, ready, blocked, sleeping.
States: visible, hidden, reduced-motion.
Tokens: original Corvi crow asset, `surface-raised`, shadow-pop, radius `lg`.
A11y: decorative animation can be paused; provide a Show/Hide Pet control and status text.
Used on: S10.

## Toast/banner

Variants: info, success, warning, error.
States: visible, dismissing, dismissed.
Tokens: matching semantic color plus `surface-raised`.
A11y: polite status for non-critical messages; assertive only for blocking errors.
Used on: all.
