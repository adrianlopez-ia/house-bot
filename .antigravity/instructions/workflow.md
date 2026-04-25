# Antigravity Workflow & Prompting

How to best work with Antigravity in this project.

## 1. Task Management
- **Plan First**: For any non-trivial change, Antigravity must create an `implementation_plan.md` and wait for approval.
- **Decomposition**: Break large features into a `task.md` checklist.
- **Incremental Updates**: Work in small chunks and verify each one.

## 2. Interactive Prompts
- **Ambiguity**: If a requirement is unclear, ask for clarification immediately instead of assuming.
- **Alternatives**: When a design decision has trade-offs, present the options to the user.
- **Feedback Loop**: After significant changes, provide a `walkthrough.md` with verification results.

## 3. Using Skills
- **Skill Activation**: If a task matches an existing "Skill" (in `.antigravity/skills/`), follow that skill's step-by-step instructions.
- **Creation**: If a repetitive task is identified, suggest creating a new Skill for it.

## 4. Modern UX (for Web parts)
- **Aesthetics**: Follow the "Design Aesthetics" from the system prompt (rich aesthetics, premium designs, no placeholders).
- **Feedback**: Ensure the UI provides clear feedback for all user actions.
