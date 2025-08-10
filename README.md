# GitLab Merge Request Summary Generator

This command-line tool generates a "What's New" summary for a GitLab Merge Request. It uses the GitLab API to fetch technical details (like commit messages and code changes) and then leverages the Google Gemini API to translate them into a clear, benefit-oriented summary suitable for non-technical clients.

## Features

-   Fetches Merge Request details, commit history, and code diffs from GitLab.
-   Uses the Gemini API to generate an intelligent, human-readable summary.
-   Formats the output in Markdown with "New Features" and "Bug Fixes" sections.
-   Creates client-friendly language by focusing on benefits, not technical jargon.
-   Includes a debug mode to inspect the exact prompt sent to the AI.

## Prerequisites

Before you begin, ensure you have the following:

-   Python 3.8+
-   A GitLab account with access to the target project.
-   A [GitLab Personal Access Token](https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html) with `api` scope.
-   A [Google Gemini API Key](https://ai.google.dev/gemini-api/docs/api-key).

## Installation

### Install with pipx (recommended)

Use pipx to install and run the CLI in an isolated virtual environment, available globally as `git-ai`:

```bash
# If you don't have pipx yet (macOS/Homebrew)
brew list pipx >/dev/null 2>&1 || brew install pipx
pipx ensurepath

# From a cloned repo or local path
git clone https://github.com/your-username/gitlab-merge-request-summary.git
cd gitlab-merge-request-summary
pipx install .

# Upgrade later
pipx upgrade git-ai
```

You can also install directly from Git using:

```bash
pipx install git+https://github.com/your-username/git-ai.git
```

After installation, the global command is `git-ai`.

### Install with pip (alternative)

```bash
pip install -r requirements.txt
```

## Configuration

This tool requires several environment variables to be set to authenticate with the GitLab and Gemini APIs.

You can set them in your shell session or add them to your shell's profile file (e.g., `~/.zshrc` or `~/.bash_profile`).

```bash
export GITLAB_URL="https://gitlab.com"
export GITLAB_PRIVATE_TOKEN="your_gitlab_personal_access_token"
export GITLAB_PROJECT_ID="your_project_id"
export GEMINI_API_KEY="your_gemini_api_key"
```

-   `GITLAB_URL`: The base URL of your GitLab instance (e.g., `https://gitlab.com`).
-   `GITLAB_PRIVATE_TOKEN`: Your GitLab Personal Access Token.
-   `GITLAB_PROJECT_ID`: The ID of your project. You can find this on your project's home page in GitLab, under the project name.
-   `GEMINI_API_KEY`: Your API key for the Google Gemini service.

### Persisting configuration (TOML)

When required values are missing, the tool will prompt you interactively and then persist them to `~/.gitlab-helper/config.toml` automatically. Subsequent runs will load values from the config file. Precedence matches AWS CLI: command-line flags > environment variables > config file. Example `config.toml`:

```toml
GITLAB_URL = "https://gitlab.com"
GITLAB_PRIVATE_TOKEN = "<your_token>"
GITLAB_PROJECT_ID = "<project_id>"
GEMINI_API_KEY = "<gemini_api_key>"
```

## Usage

After installation with pipx, use the global command `git-ai`. Replace `123` with the IID (Internal ID) of your Merge Request.

```bash
git-ai summarize <mr_id> [--style clients|devops|developers|all ...] [--debug]
```

### Code review (developers)

Generate a comprehensive code review from MR diffs:

```bash
git-ai code-review <mr_id> [--debug]
```

Outputs a `code_review_mr_<iid>.md` with structured findings (security, correctness, performance, readability, API, migrations, observability, tests, dependencies, risk/rollback) and an actionable checklist.

### Example

```bash
# All styles in one run (default)
git-ai summarize 42

# Clients style
git-ai summarize 42 --style clients

# DevOps style
git-ai summarize 42 --style devops

# Developers style
git-ai summarize 42 --style developers

# Multiple styles in one run
git-ai summarize 42 --style clients devops
```

This command will:
1.  Fetch data for Merge Request `!42` from the configured GitLab project.
2.  Generate a summary using Gemini.
3.  Print the summary to the console.
4.  Save the summary to a file named `release_summary_mr_42.<style>.md` (e.g., `release_summary_mr_42.clients.md`).

### Debug Mode

If you want to inspect the prompt that is sent to the Gemini API, you can use the `--debug` flag.

```bash
python3 main.py summarize 42 --debug
```

This will create an additional file named `debug_prompt_mr_42.<style>.md` (e.g., `debug_prompt_mr_42.clients.md`) containing the full prompt.

## Styles

Choose the `--style` that best matches your target audience. Default is `clients`.

-   **clients**: Benefit-oriented, non-technical “What’s New” for customers. Uses friendly tone and focuses on outcomes. Sections: New Features, Bug Fixes.
-   **devops**: Operational brief for DevOps/SRE. Highlights environment variables, database migrations, seeds, infrastructure/IaC, CI/CD, logging/monitoring, security, dependencies, operational tasks/runbook, and breaking changes.
-   **developers**: Technical synopsis for implementers. Sections may include: Features/Enhancements, Bug Fixes, Refactors, API Changes, Configuration (incl. env vars), Database, Dependencies/Tooling, Tests, Known Issues, Deployment Checklist.

## Output Example

The tool will generate a Markdown file with a summary similar to this:

> We've been working hard to improve your experience! This update brings some exciting new capabilities and resolves a few pesky issues. Here’s a look at what’s new.
>
> ### ✨ New Features
>
> -   **Faster & More Secure Logins:** We've completely overhauled our authentication system, making the login process quicker and more secure for your peace of mind.
> -   **New User Profile Page:** You can now view and manage your account details on a redesigned, easy-to-use profile page.
>
> ### 🐛 Bug Fixes
>
> -   Fixed an issue where the application would occasionally crash when uploading a new profile picture.
> -   Resolved a bug that caused incorrect data to be displayed on the dashboard for some users. 