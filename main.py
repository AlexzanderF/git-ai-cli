#!/usr/bin/env python3

import os
import sys
import argparse
import gitlab
import google.generativeai as genai

GEMINI_MODEL="gemini-2.5-flash"

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
        description="Generate a Release Summary for a GitLab Merge Request.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "mr_id",
        type=int,
        help="The IID (internal ID) of the Merge Request to analyze (e.g., 123)."
    )
    parser.add_argument(
        "--style",
        choices=["clients", "devops", "developers"],
        default="clients",
        help=(
            "Summary style:\n"
            "- clients: Benefit-oriented, non-technical (default)\n"
            "- devops: Operational focus (env vars, migrations, infra, logging, CI/CD)\n"
            "- developers: Technical overview for implementers"
        )
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Save the full prompt to a debug file (e.g., debug_prompt_mr_123.md)."
    )
    return parser.parse_args()

def build_prompt(style, mr, commit_messages, code_diffs):
    template = PROMPT_TEMPLATES.get(style)
    return template.format(
        mr_title=mr.title,
        mr_description=mr.description,
        commit_messages=commit_messages,
        code_diffs=code_diffs,
    )

def load_config():
    """Load required configuration from environment and exit with errors if missing."""
    
    gitlab_url = os.getenv("GITLAB_URL")
    gitlab_token = os.getenv("GITLAB_PRIVATE_TOKEN")
    project_id = os.getenv("GITLAB_PROJECT_ID")
    gemini_key = os.getenv("GEMINI_API_KEY")

    missing = []
    if not gitlab_url:
        missing.append("GITLAB_URL")
    if not gitlab_token:
        missing.append("GITLAB_PRIVATE_TOKEN")
    if not gemini_key:
        missing.append("GEMINI_API_KEY")
    if not project_id:
        missing.append("GITLAB_PROJECT_ID")

    if missing:
        print("❌ Error: Missing required environment variables: " + ", ".join(missing))
        sys.exit(1)

    return gitlab_url, gitlab_token, project_id, gemini_key

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

    gitlab_url, gitlab_token, project_id, gemini_key = load_config()
    
    # --- INITIALIZE APIS ---
    gl, model = initialize_clients(gitlab_url, gitlab_token, gemini_key)

    # --- FETCH DATA FROM GITLAB ---
    mr, commit_messages, code_diffs = fetch_mr_data(gl, project_id, args.mr_id)

    # --- 5. PROCESS WITH GEMINI ---
    prompt = build_prompt(args.style, mr, commit_messages, code_diffs)

    # Save prompt to a debug file if requested
    if args.debug:
        debug_filename = f"debug_prompt_mr_{args.mr_id}.{args.style}.md"
        if write_file(debug_filename, prompt):
            print(f"🐛 Debug prompt saved to: {debug_filename}")

    print(f"🧠 Generating a summary (style: {args.style})... (This may take a moment)")
    release_summary = generate_summary(model, prompt)

    # --- 6. SAVE OUTPUT TO FILE ---
    output_filename = f"release_summary_mr_{mr.iid}.{args.style}.md"
    if write_file(output_filename, release_summary):
        print("\n" + "="*50)
        print(f"🎉 Success! Summary saved to: {output_filename}")
        print("="*50 + "\n")
        print(release_summary)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()