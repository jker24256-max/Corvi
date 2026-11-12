# Recon map: Codex desktop app (macOS)

Scope: the core Codex desktop experience for Corvi: navigation, projects, tasks, agent activity, composer, approvals, outputs, sources, and an optional pet.
For: Abdul's personal local Corvi application.
Date: 2026-11-12

## Sources

| # | source | URL | notes |
| --- | --- | --- | --- |
| 1 | Codex product page | https://openai.com/codex/ | Public product overview and desktop screenshots. |
| 2 | Introducing the Codex app | https://openai.com/index/introducing-the-codex-app/ | Desktop app positioning, parallel agents, long-running tasks, and workflows. |
| 3 | Codex / ChatGPT desktop help | https://help.openai.com/en/articles/20001275 | Desktop navigation, Chat/Work/Codex separation, projects, recents, and pinned chats. |
| 4 | Pets documentation | https://learn.chatgpt.com/docs/pets | Optional floating pet, activity states, custom pets, and pet controls. |
| 5 | Settings reference | https://learn.chatgpt.com/docs/reference/settings | Pets, browser, computer-use, permissions, and personalization settings. |

## Core loop

Open a project, describe a coding task, let an agent inspect and modify local files with approval, review its activity/output, and continue or start another task.

## Screens

| ID | screen | route / how to reach | purpose | key components | states seen |
| --- | --- | --- | --- | --- | --- |
| S01 | Home / new task | Open Codex desktop | Start a task quickly. | Left rail, workspace selector, greeting, composer, model/location control. | Empty, ready, unavailable. |
| S02 | Task workspace | Submit a prompt or select a recent task | Follow one task from request through completion. | Task title, conversation, activity, tool calls, approvals, composer. | Running, waiting, ready, blocked, error. |
| S03 | Recent tasks | Sidebar > Recents | Resume prior work. | Search/filter, task rows, timestamps, selected state. | Empty, populated, selected. |
| S04 | Pinned tasks | Sidebar > Pinned | Keep important work close. | Pinned rows, pin/unpin action. | Empty, populated. |
| S05 | Project view | Sidebar > Projects > project | Scope work to a repository/folder. | Project name, workspace path, task list, settings. | Empty, active, permission denied. |
| S06 | Agent activity | Open a running task | Inspect what the agent is doing. | Status indicator, tool activity, terminal/browser output, progress. | Running, needs input, ready, blocked. |
| S07 | Approval view | Agent requests a risky action | Let the user approve or reject an edit/command. | Action summary, affected files, diff/command, approve/deny buttons. | Awaiting approval, approved, denied. |
| S08 | Output/source panel | Open task artifacts or research | Review generated files, sources, and results. | Outputs list, sources list, preview/open actions. | Empty, populated, unavailable. |
| S09 | Settings | App menu > Settings | Configure models, permissions, pets, tools, and preferences. | Settings navigation, toggles, selectors, refresh/reset actions. | Loaded, saving, saved, error. |
| S10 | Pet overlay | Settings > Pets or Show pet | Follow activity without opening the main window. | Floating sprite, status pose, show/hide, size, custom pet picker. | Idle, running, needs input, ready, blocked, hidden. |

## Flows

```
F01 Start a local coding task
    S01 -> S02 -> S06 -> S07 -> S06 -> S02
    happy path clicks: 1 prompt submission, 1 approval when needed
    edge: Ollama unavailable, no model installed, project permission denied

F02 Resume a previous task
    S01 -> S03 -> S02
    happy path clicks: 1 task selection
    edge: task missing, project folder disconnected, stale session

F03 Review and approve a file edit
    S02 -> S06 -> S07 -> S02
    happy path clicks: 1 approve or deny action
    edge: conflicting file change, command failure, user rejects action

F04 Inspect generated output or research sources
    S02 -> S08
    happy path clicks: 1 output/source open action
    edge: empty output, source unavailable, artifact path missing

F05 Follow work with the pet
    S02 -> S10
    happy path clicks: 1 Show pet action
    edge: hidden pet, reduced motion, pet asset unavailable
```

## Components

| component | variants | states | used on |
| --- | --- | --- | --- |
| Navigation rail | home, projects, history, settings | active, hover, disabled | all |
| Workspace menu | current workspace, switch, settings | open, closed | S01, S02, S05 |
| Task row | recent, pinned, active | default, hover, selected, unread | S03, S04 |
| Composer | text, attach, model, send | empty, focused, sending, disabled | S01, S02 |
| Status indicator | running, ready, blocked, error | animated, static | S02, S06, S10 |
| Activity card | tool, terminal, browser, research | collapsed, expanded, success, failure | S02, S06 |
| Approval card | edit, command, external action | waiting, approved, denied | S07 |
| Diff viewer | file diff, summary | clean, changed, conflict | S07, S08 |
| Output/source row | file, link, artifact | available, opened, missing | S08 |
| Pet overlay | idle, coding, thinking, sleeping, celebration | visible, hidden, reduced-motion | S10 |
| Toast/banner | info, warning, error, success | visible, dismissed | all |

## Inferred data model

```
Workspace  id, name, path, provider (local | cloud), permissions
           evidence: S01, S05, desktop help documentation
           confidence: high

Task       id, workspace_id, title, prompt, status, created_at, updated_at,
           pinned, messages, selected_model
           evidence: S02, S03, S04, official Codex task-oriented description
           confidence: high

AgentRun   id, task_id, status, started_at, finished_at, activity_items
           evidence: S06, official parallel-agent description
           confidence: medium

Approval   id, task_id, action_type, target, summary, status, decided_at
           evidence: S07, local Corvi permission behavior
           confidence: high

Artifact   id, task_id, kind, path_or_url, title, created_at
           evidence: S08, outputs/sources panel pattern
           confidence: medium

Pet       id, name, sprite_sheet, state, visible, size, position
          evidence: S10, Pets documentation
          confidence: high
```

Relationships: Workspace 1-n Task; Task 1-n AgentRun; Task 1-n Approval; Task 1-n Artifact; Workspace 1-n Pet.

## Feature matrix

See `features.csv`. Must: 17, should: 10, could: 8, skip: 2.

## Out of scope (cannot or should not be cloned)

- OpenAI's private services, internal model routing, cloud infrastructure, account system, and proprietary source code.
- OpenAI branding, copyrighted assets, and exact production UI assets; Corvi should use its own name, colors, icons, and crow pet.
- Cloud multi-device synchronization unless explicitly added later.

## Size

Screens 10, flows 5, entities 6. Hard parts: reliable local model lifecycle, streaming activity, approvals, diff rendering, task persistence, and animated pet state transitions. Size: L.

Next step: `/replica-skill:replica-architect`.
