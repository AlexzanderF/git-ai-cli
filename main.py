#!/usr/bin/env python3

import os
import sys
import argparse
import getpass
import toml
import gitlab
import google.generativeai as genai

GEMINI_MODEL="gemini-2.5-flash"
CONFIG_DIR = os.path.expanduser("~/.gitai-tool")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.toml")

# --- PROMPT TEMPLATES ---
CLIENTS_PROMPT_TEMPLATE = """
You are a Project Manager writing a "What's New" summary for our clients.
Your task is to analyze the technical data from a GitLab Merge Request, including commit messages and code diffs, to create a clear, benefit-oriented summary.

**Guidelines:**
- **Audience:** Our clients are not technical. Avoid jargon, file paths, and function names.
- **Tone:** Friendly, professional, and exciting. Be concise and to the point.
- **Format:** Use Markdown. Start with a brief, engaging overview paragraph. Then create two sections: '✨ New Features' and '🐛 Bug Fixes'.
- **Focus:** Translate technical actions into client benefits. For example, "Refactored the user auth service" should become "We've improved the speed and security of logging in."
- **Content:** Base your summary ONLY on the information provided. Ignore internal changes (e.g., CI/CD, tests, documentation) unless they have a direct client-facing impact.

**Merge Request Title:** {mr_title}
**Merge Request Description:** {mr_description}

Here is the data for the Merge Request:

--- BEGIN COMMIT MESSAGES ---
{commit_messages}
--- END COMMIT MESSAGES ---

--- BEGIN CODE CHANGES / DIFFERENCES ---
{code_diffs}
--- END CODE CHANGES / DIFFERENCES ---
"""

DEVOPS_PROMPT_TEMPLATE = """
You are a DevOps engineer preparing a release operations brief for this Merge Request.
Analyze the commit messages and code diffs and extract ONLY the operationally relevant details.

**Audience:** DevOps/SRE/Platform engineers.
**Tone:** Precise, technical, checklist-oriented.
**Output Format (Markdown):**
- Start with a short summary paragraph of the release scope in operational terms.
- Then provide the following sections with bullet points. Include only sections that have content.

### Environment Variables
- New/changed/removed variables with default values, required/optional, scope (runtime/build), and where used.

### Database Migrations
- Migration files/commands, forward/backward safety, downtime risk, data-migration steps, long-running operations.

### Seeds / Initialization Data
- Seed scripts, idempotency, when/how to run.

### Infrastructure / IaC
- Terraform/CloudFormation/K8s manifests/Helm changes, new resources, IAM/permissions, networking, storage, scaling.

### CI/CD Pipeline Changes
- New jobs, stages, approvals, required secrets, cache/artifacts, concurrency, schedules.

### Logging & Monitoring
- New log fields/levels, sinks, tracing/metrics/dashboards/alerts, sampling changes.

### Security
- Secrets management, token scopes, RBAC, exposure changes, dependency vulnerabilities.

### Dependencies & Runtime
- New/updated packages, language/runtime versions, container base images, system packages.

### Operational Tasks / Runbook
- One-time actions, manual steps, feature flags, toggles, rollback plan.

### Breaking Changes / Action Required
- Explicit callouts with required actions and ownership.

Base your brief ONLY on the provided information.

**Merge Request Title:** {mr_title}
**Merge Request Description:** {mr_description}

--- BEGIN COMMIT MESSAGES ---
{commit_messages}
--- END COMMIT MESSAGES ---

--- BEGIN CODE CHANGES / DIFFERENCES ---
{code_diffs}
--- END CODE CHANGES / DIFFERENCES ---
"""

DEVELOPERS_PROMPT_TEMPLATE = """
You are a senior software engineer writing a technical release synopsis for the developers who implemented this work.
Provide a concise, engineer-facing overview that helps verify deployment and functionality.

**Audience:** Application/backend/frontend engineers.
**Tone:** Technical, direct, action-oriented.
**Output Format (Markdown):**
- Start with a brief overview paragraph.
- Then include the following sections as relevant:
  - Features / Enhancements
  - Bug Fixes
  - Refactors / Cleanup
  - API Changes (endpoints, request/response, contracts)
  - Configuration (including env vars)
  - Database (migrations, seeds)
  - Dependencies / Tooling
  - Tests (added/updated, coverage notes)
  - Known Issues / Follow-ups
  - Deployment Checklist (verifications to perform)

Focus on what changed technically and what to verify after deploy. Avoid client-facing language.
Base your synopsis ONLY on the provided information.

**Merge Request Title:** {mr_title}
**Merge Request Description:** {mr_description}

--- BEGIN COMMIT MESSAGES ---
{commit_messages}
--- END COMMIT MESSAGES ---

--- BEGIN CODE CHANGES / DIFFERENCES ---
{code_diffs}
--- END CODE CHANGES / DIFFERENCES ---
"""

PROMPT_TEMPLATES = {
    "clients": CLIENTS_PROMPT_TEMPLATE,
    "devops": DEVOPS_PROMPT_TEMPLATE,
    "developers": DEVELOPERS_PROMPT_TEMPLATE,
}

# --- CODE REVIEW PROMPT TEMPLATE ---
CODE_REVIEW_PROMPT_TEMPLATE = """
You are a seasoned staff-level engineer performing a thorough code review of a GitLab Merge Request.
Use ONLY the provided commit messages and diffs. Do not invent context. If something is ambiguous, mark it as "Needs verification".

Produce a high-signal, developer-facing review in Markdown with the following structure. Be concrete and actionable.

1. Summary
   - One short paragraph that explains the scope and main risk areas.

2. High-Priority Findings (BLOCKER/MAJOR)
   - For each, include: [SEVERITY] File path (and function/class if visible), What’s wrong, Why it matters, How to fix (with a concise code snippet if helpful).

3. Security
   - Secrets handling, injection risks, authz/authn checks, SSRF, XSS, CSRF, path traversal, unsafe deserialization, dependency vulnerabilities.

4. Correctness & Robustness
   - Edge cases, error handling, input validation, null/None checks, off-by-one, race conditions, concurrency issues.

5. Performance
   - Hot paths, N+1 queries, unnecessary allocations, blocking I/O, inefficient algorithms, cache opportunities.

6. Readability & Maintainability
   - Naming, complexity, duplication (DRY), separation of concerns, dead code, comments/docstrings needed, file structure.

7. API & Contracts
   - Backward compatibility, request/response shape changes, error codes, pagination, headers, deprecations, versioning.

8. Data & Migrations
   - Migrations safety (forwards/backwards), data transformations, downtime risk, long-running tasks, indexes.

9. Observability
   - Logging levels/PII, metrics, tracing spans, dashboards, alerts, sampling.

10. Tests
   - Missing/fragile tests, coverage gaps, mocking issues, e2e cases to add.

11. Dependencies & Build
   - New/updated packages, licensing, supply chain, build/runtime changes.

12. Risk & Rollback
   - Feature flags/toggles, rollout plan, rollback strategy, safeguards.

Finish with:
13. Actionable Checklist
   - A concise checklist of the most important follow-ups grouped by severity.

Guidelines:
- Reference specific files and hunks when possible. Prefer: path:line range (from diff context) when the information is present.
- Use severity tags: [BLOCKER], [MAJOR], [MINOR], [NIT]. Keep nitpicks short.
- Prioritize impact and clarity over volume. Avoid generic advice.
- Do not include files or topics not present in the diffs.

Merge Request Title: {mr_title}
Merge Request Description: {mr_description}

--- BEGIN COMMIT MESSAGES ---
{commit_messages}
--- END COMMIT MESSAGES ---

--- BEGIN CODE CHANGES (WITH FILE PATHS) ---
{labeled_code_diffs}
--- END CODE CHANGES (WITH FILE PATHS) ---
"""

def parse_args():
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Git Remote Repository CLI AI Tool",
        formatter_class=argparse.RawTextHelpFormatter
    )

    subparsers = parser.add_subparsers(dest="command")

    # Common config overrides (shared across subcommands)
    common_config = argparse.ArgumentParser(add_help=False)
    common_config.add_argument(
        "--gitlab-url",
        dest="gitlab_url",
        help="Override GitLab URL (env: GITLAB_URL)."
    )
    common_config.add_argument(
        "--gitlab-private-token",
        dest="gitlab_private_token",
        help="Override GitLab Personal Access Token (env: GITLAB_PRIVATE_TOKEN)."
    )
    common_config.add_argument(
        "--gitlab-project-id",
        dest="gitlab_project_id",
        help="Override GitLab Project ID (env: GITLAB_PROJECT_ID)."
    )
    common_config.add_argument(
        "--gemini-api-key",
        dest="gemini_api_key",
        help="Override Gemini API Key (env: GEMINI_API_KEY)."
    )

    summarize = subparsers.add_parser(
        "summarize",
        help="Generate a release summary for a GitLab Merge Request.",
        formatter_class=argparse.RawTextHelpFormatter,
        parents=[common_config],
    )
    summarize.add_argument(
        "mr_id",
        type=int,
        help="The IID (internal ID) of the Merge Request to analyze (e.g., 123)."
    )
    summarize.add_argument(
        "--style",
        dest="styles",
        choices=["clients", "devops", "developers", "all"],
        nargs="+",
        default=["all"],
        help=(
            "Summary style(s). Provide one or more: clients devops developers, or 'all'.\n"
            "- clients: Benefit-oriented, non-technical (default)\n"
            "- devops: Operational focus (env vars, migrations, infra, logging, CI/CD)\n"
            "- developers: Technical overview for implementers"
        )
    )
    summarize.add_argument(
        "--debug",
        action="store_true",
        help="Save the full prompt to a debug file (e.g., debug_prompt_mr_123.md)."
    )
    # Optional overrides for config/env values are provided via common_config

    # code-review subcommand
    review = subparsers.add_parser(
        "code-review",
        help="Generate a comprehensive code review for a GitLab Merge Request.",
        formatter_class=argparse.RawTextHelpFormatter,
        parents=[common_config],
    )
    review.add_argument(
        "mr_id",
        type=int,
        help="The IID (internal ID) of the Merge Request to review (e.g., 123)."
    )
    review.add_argument(
        "--debug",
        action="store_true",
        help="Save the full prompt to a debug file (e.g., debug_code_review_mr_123.md)."
    )

    args = parser.parse_args()
    if not getattr(args, "command", None):
        parser.print_help()
        sys.exit(2)
    return args

def build_prompt(style, mr, commit_messages, code_diffs):
    template = PROMPT_TEMPLATES.get(style)
    return template.format(
        mr_title=mr.title,
        mr_description=mr.description,
        commit_messages=commit_messages,
        code_diffs=code_diffs,
    )

def _resolve_styles(requested_styles):
    if not requested_styles or "all" in requested_styles:
        return list(PROMPT_TEMPLATES.keys())
    # Deduplicate while preserving order
    seen = set()
    result = []
    for s in requested_styles:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result

def _read_config_file():
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = toml.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _write_config_file(values):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            toml.dump(values, f)
        try:
            os.chmod(CONFIG_PATH, 0o600)
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"❌ Failed to write config file at {CONFIG_PATH}: {e}")
        return False

def _prompt_for(var_name, default=None, secret=False):
    prompt = f"Enter {var_name}"
    if default:
        prompt += f" [{default}]"
    prompt += ": "
    if secret:
        value = getpass.getpass(prompt)
    else:
        value = input(prompt)
    if not value and default is not None:
        return default
    return value.strip()

def load_config(args):
    """Resolve required configuration from env, config file, or interactive prompt."""
    required_keys = [
        "GITLAB_URL",
        "GITLAB_PRIVATE_TOKEN",
        "GITLAB_PROJECT_ID",
        "GEMINI_API_KEY",
    ]

    # Load config file (lowest precedence)
    file_values = _read_config_file()
    values = {k: (str(file_values.get(k)) if file_values.get(k) is not None else None) for k in required_keys}

    # Overlay environment variables (middle precedence)
    for k in required_keys:
        env_v = os.getenv(k)
        if env_v:
            values[k] = env_v

    # Overlay CLI arguments (highest precedence)
    arg_overrides = {
        "GITLAB_URL": getattr(args, "gitlab_url", None),
        "GITLAB_PRIVATE_TOKEN": getattr(args, "gitlab_private_token", None),
        "GITLAB_PROJECT_ID": getattr(args, "gitlab_project_id", None),
        "GEMINI_API_KEY": getattr(args, "gemini_api_key", None),
    }
    for k, v in arg_overrides.items():
        if v:
            values[k] = v

    # Collect any remaining missing values via interactive prompt if TTY
    missing = [k for k in required_keys if not values.get(k)]
    if missing and sys.stdin.isatty():
        missing_list = ", ".join(missing)
        print(
            f"⚠️  Missing configuration: {missing_list}\n"
            f"You’ll be prompted now. Values will be saved to {CONFIG_PATH}\n"
            f"Precedence: CLI flags > environment variables > config file"
        )
        for k in missing:
            secret = k in ("GITLAB_PRIVATE_TOKEN", "GEMINI_API_KEY")
            default = None
            if k == "GITLAB_URL":
                default = file_values.get(k) or "https://gitlab.com"
            entered = _prompt_for(k, default=default, secret=secret)
            if not entered:
                print(f"❌ Error: {k} is required.")
                sys.exit(1)
            values[k] = entered

        # Always persist newly provided values
        to_save = {k: values[k] for k in required_keys}
        if _write_config_file(to_save):
            print(f"💾 Configuration saved to {CONFIG_PATH}")

    # Final validation
    still_missing = [k for k in required_keys if not values.get(k)]
    if still_missing:
        print("❌ Error: Missing required configuration values: " + ", ".join(still_missing))
        print("   Provide them via CLI flags, set them as environment variables, or run interactively to persist.")
        sys.exit(1)

    return (
        values["GITLAB_URL"],
        values["GITLAB_PRIVATE_TOKEN"],
        values["GITLAB_PROJECT_ID"],
        values["GEMINI_API_KEY"],
    )

def initialize_clients(gitlab_url, gitlab_token, gemini_key):
    """Initialize GitLab and Gemini clients."""
    try:
        gl = gitlab.Gitlab(gitlab_url, private_token=gitlab_token)
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(GEMINI_MODEL)
        return gl, model
    except Exception as e:
        print(f"❌ Error initializing APIs: {e}")
        sys.exit(1)

def fetch_mr_data(gl, project_id, mr_id):
    """Fetch MR, commit messages and code diffs from GitLab.

    Returns (mr, commit_messages_str, code_diffs_str, labeled_diffs_str)
    where labeled_diffs_str includes file paths as headers for better review prompts.
    """
    try:
        print(f"🔍 Fetching data for MR !{mr_id} in project {project_id}...")
        project = gl.projects.get(project_id)
        mr = project.mergerequests.get(mr_id)

        commits = list(mr.commits(all=True))
        print(f"✅ Found {len(commits)} commits.")
        commit_messages_list = [f"- {commit.title}" for commit in commits]
        commit_messages = "\n".join(commit_messages_list)

        changes = mr.changes()
        diffs_only = []
        labeled_diffs = []
        for change in changes['changes']:
            path = change.get('new_path') or change.get('old_path') or 'UNKNOWN_PATH'
            diff = change.get('diff') or ''
            diffs_only.append(diff)
            labeled_diffs.append(f"FILE: {path}\n{diff}")
        code_diffs = "\n".join(diffs_only)
        labeled_code_diffs = "\n\n".join(labeled_diffs)
        print(f"✅ Found {len(changes['changes'])} changed files.")

        return mr, commit_messages, code_diffs, labeled_code_diffs
    except gitlab.exceptions.GitlabError as e:
        print(f"❌ GitLab API Error: Could not fetch MR !{mr_id}. Status code: {e.response_code}")
        print(f"   Message: {e.error_message}")
        sys.exit(1)

def generate_summary(model, prompt):
    """Generate the summary text from the model for a given prompt."""
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"❌ An error occurred with the Gemini API: {e}")
        sys.exit(1)

def write_file(filename, content):
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    except IOError as e:
        print(f"❌ Error writing to file {filename}: {e}")
        return False

def main():
    # --- PARSE ARGUMENTS ---
    args = parse_args()

    gitlab_url, gitlab_token, project_id, gemini_key = load_config(args)

    # --- INITIALIZE APIS ---
    gl, model = initialize_clients(gitlab_url, gitlab_token, gemini_key)

    # --- FETCH DATA FROM GITLAB ---
    mr, commit_messages, code_diffs, labeled_code_diffs = fetch_mr_data(gl, project_id, args.mr_id)

    if args.command == "summarize":
        styles_to_run = _resolve_styles(getattr(args, "styles", []))
        for style in styles_to_run:
            print(f"🧠 Generating summary (style: {style})... This may take a moment")

            prompt = build_prompt(style, mr, commit_messages, code_diffs)

            # Save prompt to a debug file if requested
            if args.debug:
                debug_filename = f"debug_prompt_mr_{args.mr_id}.{style}.md"
                if write_file(debug_filename, prompt):
                    print(f"🐛 Debug prompt saved to: {debug_filename}")

            release_summary = generate_summary(model, prompt)

            output_filename = f"release_summary_mr_{mr.iid}.{style}.md"
            if write_file(output_filename, release_summary):
                print("\n" + "="*50)
                print(f"🎉 Success! Summary saved to: {output_filename}")
                print("="*50 + "\n")
                print(release_summary)
            else:
                sys.exit(1)

    # Handle code-review subcommand
    if args.command == "code-review":
        # Build code review prompt using labeled diffs for file context
        review_prompt = CODE_REVIEW_PROMPT_TEMPLATE.format(
            mr_title=mr.title,
            mr_description=mr.description,
            commit_messages=commit_messages,
            labeled_code_diffs=labeled_code_diffs,
        )
        if args.debug:
            debug_filename = f"debug_code_review_prompt_mr_{args.mr_id}.md"
            if write_file(debug_filename, review_prompt):
                print(f"🐛 Debug code review prompt saved to: {debug_filename}")

        print("🧠 Generating code review... This may take a moment")
        review_output = generate_summary(model, review_prompt)
        review_filename = f"code_review_mr_{mr.iid}.md"
        if write_file(review_filename, review_output):
            print("\n" + "="*50)
            print(f"🎉 Success! Code review saved to: {review_filename}")
            print("="*50 + "\n")
            print(review_output)
        else:
            sys.exit(1)

if __name__ == "__main__":
    main()