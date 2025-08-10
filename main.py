#!/usr/bin/env python3

import os
import sys
import argparse
import getpass
import toml
import gitlab
import google.generativeai as genai

GEMINI_MODEL="gemini-2.5-flash"
CONFIG_DIR = os.path.expanduser("~/.gitlab-helper")
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

def parse_args():
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="GitLab helper CLI",
        formatter_class=argparse.RawTextHelpFormatter
    )

    subparsers = parser.add_subparsers(dest="command")

    summarize = subparsers.add_parser(
        "summarize",
        help="Generate a release summary for a GitLab Merge Request.",
        formatter_class=argparse.RawTextHelpFormatter,
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
    # Optional overrides for config/env values (highest precedence if provided)
    summarize.add_argument(
        "--gitlab-url",
        dest="gitlab_url",
        help="Override GitLab URL (env: GITLAB_URL)."
    )
    summarize.add_argument(
        "--gitlab-private-token",
        dest="gitlab_private_token",
        help="Override GitLab Personal Access Token (env: GITLAB_PRIVATE_TOKEN)."
    )
    summarize.add_argument(
        "--gitlab-project-id",
        dest="gitlab_project_id",
        help="Override GitLab Project ID (env: GITLAB_PROJECT_ID)."
    )
    summarize.add_argument(
        "--gemini-api-key",
        dest="gemini_api_key",
        help="Override Gemini API Key (env: GEMINI_API_KEY)."
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
    """Fetch MR, commit messages and code diffs from GitLab."""
    try:
        print(f"🔍 Fetching data for MR !{mr_id} in project {project_id}...")
        project = gl.projects.get(project_id)
        mr = project.mergerequests.get(mr_id)

        commits = list(mr.commits(all=True))
        print(f"✅ Found {len(commits)} commits.")
        commit_messages_list = [f"- {commit.title}" for commit in commits]
        commit_messages = "\n".join(commit_messages_list)

        changes = mr.changes()
        code_diffs = "\n".join([change['diff'] for change in changes['changes']])
        print(f"✅ Found {len(changes['changes'])} changed files.")

        return mr, commit_messages, code_diffs
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
    mr, commit_messages, code_diffs = fetch_mr_data(gl, project_id, args.mr_id)

    styles_to_run = _resolve_styles(args.styles)

    for style in styles_to_run:
        print(f"🧠 Generating summary (style: {style})... This may take a moment")
        # --- 5. PROCESS WITH GEMINI ---
        prompt = build_prompt(style, mr, commit_messages, code_diffs)

        # Save prompt to a debug file if requested
        if args.debug:
            debug_filename = f"debug_prompt_mr_{args.mr_id}.{style}.md"
            if write_file(debug_filename, prompt):
                print(f"🐛 Debug prompt saved to: {debug_filename}")

        release_summary = generate_summary(model, prompt)

        # --- 6. SAVE OUTPUT TO FILE ---
        output_filename = f"release_summary_mr_{mr.iid}.{style}.md"
        if write_file(output_filename, release_summary):
            print("\n" + "="*50)
            print(f"🎉 Success! Summary saved to: {output_filename}")
            print("="*50 + "\n")
            print(release_summary)
        else:
            sys.exit(1)

if __name__ == "__main__":
    main()