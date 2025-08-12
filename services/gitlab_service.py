import sys
import gitlab
import os

def fetch_mr_summary_data(gl, project_id, mr_id):
    """Fetch MR, commit messages and code diffs from GitLab for summary generation."""
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
        for change in changes['changes']:
            diff = change.get('diff') or ''
            diffs_only.append(diff)
        code_diffs = "\n".join(diffs_only)
        print(f"✅ Found {len(changes['changes'])} changed files.")

        return mr, commit_messages, code_diffs
    except gitlab.exceptions.GitlabError as e:
        print(f"❌ GitLab API Error: Could not fetch MR !{mr_id}. Status code: {e.response_code}")
        print(f"   Message: {e.error_message}")
        sys.exit(1)

def fetch_mr_code_review_data(gl, project_id, mr_id):
    """Fetch MR, commit messages and code diffs from GitLab for code review."""
    try:
        print(f"🔍 Fetching data for MR !{mr_id} in project {project_id}...")
        project = gl.projects.get(project_id)
        mr = project.mergerequests.get(mr_id)

        print(f"🔍 MR SOURCE BRANCH: {mr.source_branch}")

        commits = list(mr.commits(all=True))
        print(f"✅ Found {len(commits)} commits.")
        commit_messages_list = [f"- {commit.title}" for commit in commits]
        commit_messages = "\n".join(commit_messages_list)

        # --- Diffs and Full File Contents ---
        changes = mr.changes()
        labeled_diffs = []
        full_files_content = []
        print(f"✅ Found {len(changes['changes'])} changed files. Fetching full content...")
        
        for change in changes['changes']:
            diff = change.get('diff') or ''
            # Only process if there's a diff and it's not a deleted file
            if not diff or change.get('deleted_file'):
                continue

            path = change.get('new_path')
            labeled_diffs.append(f"--- FILE DIFF: {path} ---\n{diff}")
            
            # Fetch the full file content from the source branch
            try:
                # Get the directory path and file name
                dir_path = os.path.dirname(path)
                file_name = os.path.basename(path)

                # List the files in the directory to find our file's blob_id
                tree = project.repository_tree(path=dir_path, ref=mr.source_branch, all=True)
                blob_id = None
                for item in tree:
                    if item['name'] == file_name:
                        blob_id = item['id']
                        break
                
                # Get raw blob content using the blob_id
                file_content_bytes = project.repository_raw_blob(blob_id)
                file_content = file_content_bytes.decode('utf-8')
                
                full_files_content.append(f"--- BEGIN FULL FILE CONTENT: {path} ---\n{file_content}\n--- END FULL FILE CONTENT: {path} ---")
            except Exception as e:
                print(f"❌ Error: Could not fetch full file content for {path}. {e}")
        
        labeled_code_diffs = "\n\n".join(labeled_diffs)
        full_files_content_str = "\n\n".join(full_files_content)
        
        return mr, commit_messages, labeled_code_diffs, full_files_content_str
    except gitlab.exceptions.GitlabError as e:
        print(f"❌ GitLab API Error: Could not fetch MR !{mr_id}. Status code: {e.response_code}")
        print(f"   Message: {e.error_message}")
        sys.exit(1)