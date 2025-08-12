#!/usr/bin/env python3

import os
import sys
import argparse
import getpass
import toml
import gitlab
import google.generativeai as genai
from services.gitlab_service import fetch_mr_summary_data, fetch_mr_code_review_data
from services.promts_service import build_summary_prompt, build_code_review_prompt, SUMMARY_PROMPT_STYLES_TEMPLATES

DEFAULT_MODEL = "gemini-2.5-flash"
CONFIG_DIR = os.path.expanduser("~/.gitai-tool")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.toml")

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
    common_config.add_argument(
        "--model",
        dest="model",
        default=DEFAULT_MODEL,
        help=(f"Gemini model identifier. Defaults to '{DEFAULT_MODEL}'."),
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

def _validate_selected_styles(requested_styles):
    if not requested_styles or "all" in requested_styles:
        return list(SUMMARY_PROMPT_STYLES_TEMPLATES.keys())
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

def initialize_clients(gitlab_url, gitlab_token, gemini_key, model_name):
    """Initialize GitLab and Gemini clients."""
    try:
        gl = gitlab.Gitlab(gitlab_url, private_token=gitlab_token)
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(model_name)
        return gl, model
    except Exception as e:
        print(f"❌ Error initializing APIs: {e}")
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
    gl, model = initialize_clients(gitlab_url, gitlab_token, gemini_key, getattr(args, "model", DEFAULT_MODEL))

    # Handle summarize subcommand
    if args.command == "summarize":
        # --- FETCH DATA FROM GITLAB ---
        mr, commit_messages, code_diffs = fetch_mr_summary_data(gl, project_id, args.mr_id)

        styles_to_run = _validate_selected_styles(getattr(args, "styles", []))
        for style in styles_to_run:
            print(f"🧠 Generating summary (style: {style})... This may take a moment")

            prompt = build_summary_prompt(style, mr, commit_messages, code_diffs)

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
        # --- FETCH DATA FROM GITLAB ---
        mr, commit_messages, labeled_code_diffs, full_files_content = fetch_mr_code_review_data(gl, project_id, args.mr_id)

        # Build code review prompt using labeled diffs for file context
        review_prompt = build_code_review_prompt(mr, commit_messages, labeled_code_diffs, full_files_content)

        # Save prompt to a debug file if requested
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