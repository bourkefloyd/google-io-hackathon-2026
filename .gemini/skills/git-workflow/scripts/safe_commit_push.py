#!/usr/bin/env python3
"""
Interactive, colorized Conventional Commits and Safe Push Assistant.
Integrates workspace quality gates (formatting, linting, tests) with git safety loops.
"""

import argparse
import os
import subprocess
import sys

# Premium Terminal Colors
CYAN = "\033[1;36m"
YELLOW = "\033[1;33m"
GREEN = "\033[1;32m"
RED = "\033[1;31m"
MAGENTA = "\033[1;35m"
BOLD = "\033[1m"
RESET = "\033[0m"

COMMIT_TYPES = [
    ("feat", "A new feature (corresponds to MINOR in SemVer)"),
    ("fix", "A bug fix (corresponds to PATCH in SemVer)"),
    ("docs", "Documentation only changes"),
    ("style", "Changes that do not affect the meaning of the code (formatting, etc.)"),
    ("refactor", "A code change that neither fixes a bug nor adds a feature"),
    ("perf", "A code change that improves performance"),
    ("test", "Adding missing tests or correcting existing tests"),
    ("build", "Changes that affect the build system or external dependencies"),
    ("ci", "Changes to CI configuration files and scripts"),
    ("chore", "Other changes that don't modify src or test files"),
    ("revert", "Reverts a previous commit")
]


def log_header(title):
    print(f"\n{CYAN}{'='*70}{RESET}")
    print(f"⚡ {BOLD}{CYAN}{title}{RESET} ⚡")
    print(f"{CYAN}{'='*70}{RESET}")


def log_step(message):
    print(f"{CYAN}➜ {RESET}{message}")


def log_success(message):
    print(f"{GREEN}✔ {RESET}{message}")


def log_warn(message):
    print(f"{YELLOW}⚠ {RESET}{message}")


def log_error(message):
    print(f"{RED}✘ {RESET}{message}")


def run_command(cmd, cwd=None):
    """Runs a system command, returning its stdout if successful, raising exception on failure."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else e.stdout.strip()
        raise RuntimeError(f"Command '{cmd}' failed (exit code {e.returncode}): {error_msg}")


def check_git_status():
    """Checks git state and returns list of changed/staged files."""
    try:
        # Check if inside git repo
        run_command("git rev-parse --is-inside-work-tree")
    except RuntimeError:
        log_error("Not in a git repository!")
        sys.exit(1)

    status_out = run_command("git status --porcelain")
    if not status_out:
        log_warn("Working tree is completely clean. Nothing to commit or push.")
        return []

    print(f"\n{MAGENTA}--- Modified / Untracked Files ---{RESET}")
    print(status_out)
    return status_out.splitlines()


def run_quality_gates():
    """Runs make format, lint, and test to ensure code passes quality checks."""
    log_header("Running Automated Quality Gates")

    try:
        log_step("Executing auto-formatter (make format)...")
        run_command("make format")
        log_success("Formatting checks passed successfully.")

        log_step("Executing static analysis checks (make lint)...")
        run_command("make lint")
        log_success("Linter analysis complete. Code is clean.")

        log_step("Executing path and import integrity tests (make test)...")
        test_out = run_command("make test")
        print(f"\n{GREEN}{test_out}{RESET}\n")
        log_success("Integrity and path testing passed perfectly.")
    except RuntimeError as e:
        log_error(f"Quality gate failure: {e}")
        log_error("Commit aborted. Please fix errors and try again.")
        sys.exit(1)


def build_message_interactively():
    """Guides the user through building a Conventional Commit message."""
    log_header("Conventional Commit Constructor")

    print(f"{YELLOW}Select the type of change you are committing:{RESET}")
    for idx, (t, desc) in enumerate(COMMIT_TYPES, 1):
        print(f"  {CYAN}{idx:2d}. {BOLD}{t:<10}{RESET} {desc}")

    selected_type = ""
    while True:
        try:
            choice = input(f"\nEnter choice [1-{len(COMMIT_TYPES)}]: ").strip()
            if not choice:
                continue
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(COMMIT_TYPES):
                selected_type = COMMIT_TYPES[choice_idx][0]
                break
            else:
                log_error("Invalid index. Choose one of the listed options.")
        except ValueError:
            # Check if they typed the type name directly
            matching_types = [t for t, _ in COMMIT_TYPES if t == choice.lower()]
            if matching_types:
                selected_type = matching_types[0]
                break
            log_error("Please enter a valid option number or type name.")

    log_success(f"Selected type: {BOLD}{selected_type}{RESET}")

    scope = input(f"\nEnter optional scope (e.g. auth, telemetry) [Press Enter to skip]: ").strip()
    if scope:
        scope = f"({scope})"

    description = ""
    while not description:
        description = input(f"\nEnter short imperative description (lowercase, no ending period): ").strip()
        if not description:
            log_error("Description cannot be empty.")
        elif description[0].isupper():
            log_warn("Description should start with a lowercase letter.")
            # Auto convert first char if desired, or keep as warning
        elif description.endswith('.'):
            log_warn("Description should not end with a period.")
            description = description.rstrip('.')

    body = []
    print(f"\nEnter optional detailed body [Press Enter on empty line to finish]:")
    while True:
        line = input("> ").strip()
        if not line:
            break
        body.append(line)
    body_str = "\n".join(body) if body else ""

    is_breaking = input(f"\nIs this a breaking change? (y/n) [n]: ").strip().lower() == 'y'
    breaking_footer = ""
    if is_breaking:
        # Append bang to type/scope prefix
        selected_type = f"{selected_type}!"
        breaking_desc = input(f"Enter description of breaking change (mandatory): ").strip()
        while not breaking_desc:
            log_error("Breaking change description is mandatory.")
            breaking_desc = input(f"Enter description of breaking change (mandatory): ").strip()
        breaking_footer = f"BREAKING CHANGE: {breaking_desc}"

    footer_lines = []
    has_issues = input(f"\nDoes this resolve or reference any open issues? (y/n) [n]: ").strip().lower() == 'y'
    if has_issues:
        issue_refs = input(f"Enter issue numbers / footers (e.g. Closes #123, Refs #456): ").strip()
        if issue_refs:
            footer_lines.append(issue_refs)

    if breaking_footer:
        footer_lines.insert(0, breaking_footer)

    footers_str = "\n".join(footer_lines) if footer_lines else ""

    # Compile Conventional Commit Message
    header = f"{selected_type}{scope}: {description}"
    full_message = header
    if body_str:
        full_message += f"\n\n{body_str}"
    if footers_str:
        full_message += f"\n\n{footers_str}"

    return full_message


def safe_sync_and_push(dry_run):
    """Fetches upstream changes, performs a safe rebase, and pushes changes."""
    log_header("Syncing and Pushing Safely")

    current_branch = run_command("git branch --show-current")
    log_step(f"Current active branch: {BOLD}{current_branch}{RESET}")

    if dry_run:
        log_step(f"[DRY-RUN] Would run: git fetch origin && git rebase origin/{current_branch}")
        log_step(f"[DRY-RUN] Would run: git push origin {current_branch}")
        log_success("[DRY-RUN] Safe sync and push validated.")
        return

    try:
        log_step("Fetching upstream changes...")
        run_command("git fetch origin")

        # Check if remote branch exists
        remote_exists = False
        try:
            run_command(f"git rev-parse --verify origin/{current_branch}")
            remote_exists = True
        except RuntimeError:
            log_warn(f"Remote branch origin/{current_branch} does not exist yet. Will create on push.")

        if remote_exists:
            log_step("Performing safe rebase onto remote changes...")
            run_command(f"git rebase origin/{current_branch}")
            log_success("Rebase finished successfully. Local branch is in sync with upstream.")

        log_step("Pushing commits to remote repository...")
        run_command(f"git push origin {current_branch}")
        log_success("Code pushed successfully!")
    except RuntimeError as e:
        log_error(f"Sync or Push failed: {e}")
        log_warn("Please inspect git status and resolve conflicts manually if needed.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Enforce Conventional Commits and safe quality gates before committing/pushing."
    )
    parser.add_argument("-t", "--type", help="Commit type (feat, fix, docs, style, refactor, perf, test, build, etc.)")
    parser.add_argument("-s", "--scope", help="Optional scope surrounding parentheses")
    parser.add_argument("-m", "--message", help="Short imperative description of change")
    parser.add_argument("-b", "--body", help="Optional detailed body")
    parser.add_argument("-f", "--footer", help="Optional footer or breaking change detail")
    parser.add_argument("-d", "--dry-run", action="store_true", help="Dry run mode. Only validates and compiles message.")
    parser.add_argument("--skip-checks", action="store_true", help="Skip running Makefile quality checks.")
    parser.add_argument("-y", "--yes", action="store_true", help="Non-interactive execution. Bypasses confirmations.")

    args = parser.parse_args()

    # Check git working tree
    files = check_git_status()
    if not files:
        sys.exit(0)

    # 1. Quality Gates
    if not args.skip_checks:
        run_quality_gates()
    else:
        log_warn("Quality checks skipped by user.")

    # 2. Build Commit Message
    is_interactive = not (args.type and args.message)

    if is_interactive:
        commit_msg = build_message_interactively()
    else:
        # Enforce validation on provided arguments
        c_type = args.type.lower()
        valid_types = [t for t, _ in COMMIT_TYPES]
        if c_type.endswith("!"):
            c_base = c_type[:-1]
        else:
            c_base = c_type

        if c_base not in valid_types:
            log_error(f"Invalid type: '{args.type}'. Must be one of: {', '.join(valid_types)}")
            sys.exit(1)

        scope_str = f"({args.scope})" if args.scope else ""
        commit_msg = f"{c_type}{scope_str}: {args.message}"
        if args.body:
            commit_msg += f"\n\n{args.body}"
        if args.footer:
            commit_msg += f"\n\n{args.footer}"

    # 3. Present Message & Confirm
    log_header("Compiled Commit Message")
    print(f"{YELLOW}{'='*70}{RESET}")
    print(commit_msg)
    print(f"{YELLOW}{'='*70}{RESET}\n")

    if args.dry_run:
        log_success("[DRY-RUN] Commit message validated successfully.")
        safe_sync_and_push(dry_run=True)
        sys.exit(0)

    if is_interactive and not args.yes:
        confirm = input(f"{YELLOW}Proceed with staging all modifications and committing? (y/n) [y]: {RESET}").strip().lower()
        if confirm not in ("", "y", "yes"):
            log_warn("Aborted commit.")
            sys.exit(0)

    # 4. Git Add and Commit
    try:
        log_step("Staging all modifications and untracked changes...")
        run_command("git add .")
        log_success("All workspace changes successfully staged.")

        log_step("Committing changes...")
        # Write message to temp file to support multi-line commits reliably
        temp_msg_file = ".git_commit_msg.tmp"
        with open(temp_msg_file, "w") as f:
            f.write(commit_msg)

        run_command(f"git commit -F {temp_msg_file}")
        os.remove(temp_msg_file)
        log_success("Commit finalized successfully.")
    except Exception as e:
        log_error(f"Commit execution failed: {e}")
        if os.path.exists(".git_commit_msg.tmp"):
            os.remove(".git_commit_msg.tmp")
        sys.exit(1)

    # 5. Safe sync and push
    if is_interactive and not args.yes:
        confirm_push = input(f"\n{YELLOW}Proceed with pulling updates and pushing commits to remote? (y/n) [y]: {RESET}").strip().lower()
        if confirm_push not in ("", "y", "yes"):
            log_warn("Pushed skipped. Commits remain local.")
            sys.exit(0)

    safe_sync_and_push(dry_run=False)


if __name__ == "__main__":
    main()
