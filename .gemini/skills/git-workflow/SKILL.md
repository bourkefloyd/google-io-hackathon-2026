---
name: git-workflow
description: "Safely execute commits and pushes in the workspace using the Conventional Commits v1.0.0 standard and automated quality checks."
---

# Git Workflow Project Skill

This skill governs standard procedures for committing and pushing updates within this repository safely, ensuring clean git history and protecting branch integrity.

---

## 1. Conventional Commits v1.0.0 Specification

All commit messages MUST follow the **Conventional Commits v1.0.0** specifications. This structure enhances searchability, enables automated changelog generation, and correlates directly with Semantic Versioning (SemVer).

### Structure
```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

### Commit Types (`<type>`)
- **`feat`**: A new feature is added (corresponds to a `MINOR` release in SemVer).
- **`fix`**: A bug fix is implemented (corresponds to a `PATCH` release in SemVer).
- **`docs`**: Changes only affect documentation.
- **`style`**: Changes that do not affect the meaning of the code (formatting, white-space, semi-colons, etc.).
- **`refactor`**: Code changes that neither fix a bug nor add a feature.
- **`perf`**: A code change that improves performance.
- **`test`**: Adding missing tests or correcting existing tests.
- **`build`**: Changes that affect the build system or external dependencies (e.g., pip, npm, Makefile).
- **`ci`**: Changes to CI configuration files and scripts (e.g., GitHub Actions).
- **`chore`**: Other changes that don't modify src or test files (e.g., updating `.gitignore`).
- **`revert`**: Reverts a previous commit.

### Structural Elements
1. **Scope (Optional)**: A noun describing a section of the codebase surrounded by parentheses (e.g., `feat(auth): add google sign-in`).
2. **Description**: A short summary of the code changes. Use the imperative, present tense: "change" not "changed" nor "changes". No capitalization at the start, and no period at the end.
3. **Body (Optional)**: Provides detailed explanatory information regarding the change. Should be separated from the description by a single blank line.
4. **Footer / Breaking Change (Optional)**: Used to document breaking changes (prefixed with `BREAKING CHANGE: ` or appending a `!` after type/scope) and reference issue/PR tracker tickets (e.g., `Close #123`).

### Conventional Commit Examples
- **Basic Feature:**
  ```
  feat(telemetry): implement sse connection broker
  ```
- **Bug Fix:**
  ```
  fix(adb): resolve pixel resolution scaling error
  ```
- **Breaking Change (via symbol):**
  ```
  feat(ingestion)!: migrate local telemetry payload layout
  ```
- **Breaking Change (via footer):**
  ```
  fix(server): restrict config endpoint access

  BREAKING CHANGE: The config endpoint now requires valid bearer tokens.
  ```

---

## 2. Safe Pre-Commit Quality Gates

Never commit dirty, unformatted, or broken code. Before committing, the local quality suite MUST be run and pass:

1. **Auto-Formatting**: Run pep8 code formatting.
   ```bash
   make format
   ```
2. **Lint Checks**: Run static code analysis to catch syntax, style, and potential logic bugs.
   ```bash
   make lint
   ```
3. **Module Integrity Tests**: Run local path and import verification checks to guarantee stability.
   ```bash
   make test
   ```

*Note: The commit cycle must abort immediately if any linter or unit test fails.*

---

## 3. Safe Sync and Pull Workflow

To prevent merge conflicts and ensure clean history, always pull upstream changes before attempting to push.

1. **Save Local Work**: If you have changes you are not ready to commit, stash them:
   ```bash
   git stash
   ```
2. **Fetch and Rebase**: Fetch remote modifications and reapply local commits on top of them:
   ```bash
   git fetch origin
   git rebase origin/main
   ```
3. **Restore Local Work**: If stashed, bring back local modifications:
   ```bash
   git stash pop
   ```

---

## 4. Automated Commit & Push Assistant

To simplify this process, we have provided an automated, interactive Python script:
`.gemini/skills/git-workflow/scripts/safe_commit_push.py`

This script automates:
- Executing quality gates (`make format`, `make lint`, `make test`).
- Prompting for Conventional Commit components.
- Staging and committing changes with valid formatting.
- Safely fetching, rebasing, and pushing changes.

You can run the script manually or inside the IDE terminal:
```bash
python3 .gemini/skills/git-workflow/scripts/safe_commit_push.py
```
Use the `--dry-run` flag to validate the workflow without executing git commits or pushes:
```bash
python3 .gemini/skills/git-workflow/scripts/safe_commit_push.py --dry-run
```
