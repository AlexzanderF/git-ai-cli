#!/usr/bin/env python3

import os
import sys
import argparse
import gitlab
import google.generativeai as genai

GEMINI_MODEL="gemini-2.5-flash"

def main():
    # --- PARSE ARGUMENTS ---
    parser = argparse.ArgumentParser(
        description="Generate a Release Summary for a GitLab Merge Request.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "mr_id",
        type=int,
        help="The IID (internal ID) of the Merge Request to analyze (e.g., 123)."
    )
    args = parser.parse_args()

    gitlab_url = os.getenv("GITLAB_URL")
    gitlab_token = os.getenv("GITLAB_PRIVATE_TOKEN")
    project_id = os.getenv("GITLAB_PROJECT_ID")
    gemini_key = os.getenv("GEMINI_API_KEY")

    # Check each required variable individually
    if not gitlab_url:
        print("❌ Error: Missing GITLAB_URL")
        sys.exit(1)
    if not gitlab_token:
        print("❌ Error: Missing GITLAB_PRIVATE_TOKEN")
        sys.exit(1)
    if not gemini_key:
        print("❌ Error: Missing GEMINI_API_KEY")
        sys.exit(1)
    if not project_id:
        print("❌ Error: Missing GITLAB_PROJECT_ID")
        sys.exit(1)
    
    # --- INITIALIZE APIS ---
    try:
        gl = gitlab.Gitlab(gitlab_url, private_token=gitlab_token)
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(GEMINI_MODEL)
    except Exception as e:
        print(f"❌ Error initializing APIs: {e}")
        sys.exit(1)

    # --- FETCH DATA FROM GITLAB ---
    try:
        print(f"🔍 Fetching data for MR !{args.mr_id} in project {project_id}...")
        project = gl.projects.get(project_id)
        mr = project.mergerequests.get(args.mr_id)

        # Get commit messages with branch info
        commits = list(mr.commits(all=True))
        print(f"✅ Found {len(commits)} commits.")

        commit_messages_list = []
        for i, commit in enumerate(commits):
            commit_title = f"- {commit.title}"
            try:
                # This makes an API call for each commit to get its refs (branches/tags)
                full_commit = project.commits.get(commit.id)
                refs = full_commit.refs.list(all=True)

                # Filter for branches, excluding the MR's own source and target branches
                branches = [
                    ref.name for ref in refs
                    if ref.type == 'branch' and
                       ref.name != mr.source_branch and
                       ref.name != mr.target_branch
                ]

                if branches:
                    # Take the first associated branch assumed to be where the commit was made.
                    original_branch = branches[0]
                    # Extract the category from the branch name (e.g., 'feature' from 'feature/add-button')
                    branch_type = original_branch.split('/')[0]
                    commit_title += f" ({branch_type})"

            except gitlab.exceptions.GitlabError as e:
                pass

            commit_messages_list.append(commit_title)

        commit_messages = "\n".join(commit_messages_list)

        # Get code diffs
        changes = mr.changes()
        # Combine all diffs into a single string for the prompt
        code_diffs = "\n".join([change['diff'] for change in changes['changes']])
        
        print(f"✅ Found {len(changes['changes'])} changed files.")

    except gitlab.exceptions.GitlabError as e:
        print(f"❌ GitLab API Error: Could not fetch MR !{args.mr_id}. Status code: {e.response_code}")
        print(f"   Message: {e.error_message}")
        sys.exit(1)

    # --- 5. PROCESS WITH GEMINI ---
    prompt = f"""
    You are a Project Manager writing a "What's New" summary for our clients.
    Your task is to analyze the technical data from a GitLab Merge Request, including commit messages and code diffs, to create a clear, benefit-oriented summary.

    **Guidelines:**
    - **Audience:** Our clients are not technical. Avoid jargon, file paths, and function names.
    - **Tone:** Friendly, professional, and exciting.
    - **Format:** Use Markdown. Start with a brief, engaging overview paragraph. Then create two sections: '✨ New Features' and '🐛 Bug Fixes'.
    - **Focus:** Translate technical actions into client benefits. For example, "Refactored the user auth service" should become "We've improved the speed and security of logging in."
    - **Content:** Base your summary ONLY on the information provided. Ignore internal changes (e.g., CI/CD, tests, documentation) unless they have a direct client-facing impact.

    **Merge Request Title:** {mr.title}
    **Merge Request Description:** {mr.description}
    
    Here is the data for the Merge Request:

    --- BEGIN COMMIT MESSAGES ---
    {commit_messages}
    --- END COMMIT MESSAGES ---

    --- BEGIN CODE CHANGES / DIFFERENCES ---
    {code_diffs}
    --- END CODE CHANGES / DIFFERENCES ---
    """

    print("🧠 Generating a summary... (This may take a moment)")
    
    # Save prompt to a debug file
    debug_filename = f"debug_prompt_mr_{args.mr_id}.md"
    try:
        with open(debug_filename, 'w', encoding='utf-8') as f:
            f.write(prompt)
    except IOError as e:
        pass
        
    try:
        response = model.generate_content(prompt)
        release_summary = response.text
    except Exception as e:
        print(f"❌ An error occurred with the Gemini API: {e}")
        sys.exit(1)

    # --- 6. SAVE OUTPUT TO FILE ---
    output_filename = f"release_summary_mr_{mr.iid}.md"
    try:
        with open(output_filename, 'w', encoding='utf-8') as f:
            f.write(release_summary)
        print("\n" + "="*50)
        print(f"🎉 Success! Summary saved to: {output_filename}")
        print("="*50 + "\n")
        # Also print the summary to the console for a quick preview
        print(release_summary)
    except IOError as e:
        print(f"❌ Error writing to file {output_filename}: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()