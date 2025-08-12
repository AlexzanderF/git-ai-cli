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

SUMMARY_PROMPT_STYLES_TEMPLATES = {
    "clients": CLIENTS_PROMPT_TEMPLATE,
    "devops": DEVOPS_PROMPT_TEMPLATE,
    "developers": DEVELOPERS_PROMPT_TEMPLATE,
}

# --- CODE REVIEW PROMPT TEMPLATE ---
CODE_REVIEW_PROMPT_TEMPLATE = """
You are an expert Senior Software Engineer performing a thorough code review of a GitLab Merge Request.
Use ONLY the provided changes/diffs and the full file contents for more context about the changes. Do not invent context. If something is ambiguous, mark it as "Needs verification".
Do the review ONLY on the changes, not on the entire codebase. Skip reviewing changes like indentations, newlines, whitespace, empty lines, etc.

Produce a high-signal, developer-facing review in Markdown with the following structure. Be concrete and actionable.

1. High-Priority Findings (BLOCKER/MAJOR)
   - For each, include: [SEVERITY] File path (and function/class if visible), What’s wrong, Why it matters.

2. Correctness & Robustness
   - Edge cases, error handling, input validation, null/None checks, off-by-one, race conditions, concurrency issues, misspelled variables, etc.

3. Security
   - Secrets handling, injection risks, authz/authn checks, SSRF, XSS, CSRF, path traversal, unsafe deserialization, dependency vulnerabilities.
   
4. Performance
   - Hot paths, N+1 queries, unnecessary allocations, blocking I/O, inefficient algorithms, cache opportunities.

5. Readability & Maintainability
   - Naming, complexity, duplication (DRY), separation of concerns, dead code, comments/docstrings needed, file structure.

6. API & Contracts
   - Backward compatibility, request/response shape changes, error codes, pagination, headers, deprecations, versioning.

7. Data & Migrations
   - Migrations safety (forwards/backwards), data transformations, downtime risk, long-running tasks, indexes.

8. Dependencies & Build
   - New/updated packages, licensing, supply chain, build/runtime changes.

9. Risk & Rollback
   - Feature flags/toggles, rollout plan, rollback strategy, safeguards.

Finish with:
   Actionable Checklist
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

Here are the full contents of the changed files for context:
--- BEGIN FULL FILE CONTENTS ---
{full_files_content}
--- END FULL FILE CONTENTS ---

Here are the specific diffs to review within those files:
--- BEGIN CODE CHANGES (WITH FILE PATHS) ---
{labeled_code_diffs}
--- END CODE CHANGES (WITH FILE PATHS) ---
"""

def build_summary_prompt(style, mr, commit_messages, code_diffs):
    template = SUMMARY_PROMPT_STYLES_TEMPLATES.get(style)
    return template.format(
        mr_title=mr.title,
        mr_description=mr.description,
        commit_messages=commit_messages,
        code_diffs=code_diffs,
    )

def build_code_review_prompt(mr, commit_messages, labeled_code_diffs, full_files_content):
    return CODE_REVIEW_PROMPT_TEMPLATE.format(
        mr_title=mr.title,
        mr_description=mr.description,
        commit_messages=commit_messages,
        labeled_code_diffs=labeled_code_diffs,
        full_files_content=full_files_content,
    )