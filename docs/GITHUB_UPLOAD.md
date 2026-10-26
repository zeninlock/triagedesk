# Publishing TriageDesk to GitHub

This guide publishes the project source, documentation, screenshots, and recorded evaluation evidence. It does not deploy the application or publish its separate real-data bundle.

## 1. Choose the correct project folder

Use the folder containing `README.md`, `compose.yaml`, `src/`, `ui/`, and `tests/`.

The repository root should look like this:

```text
README.md
LICENSE
.gitignore
.env.example
.github/workflows/ci.yml
compose.yaml
Dockerfile
pyproject.toml
uv.lock
src/
ui/
tests/
docs/
...
```

Use the actual `triagedesk` project directory, not the parent output directory. If starting from the ZIP delivery, extract it first. Commit the extracted source files rather than uploading the ZIP as the repository's only file.

The existing `.gitignore` excludes local settings, virtual environments, generated data/models, database dumps, caches, and the separate snapshot archive. The `.env.example` file intentionally contains documented local demonstration credentials. Real credentials belong in the ignored `.env` file.

## 2. Recommended option: GitHub Desktop

GitHub Desktop provides browser-based account sign-in and a visual file review.

1. Install [GitHub Desktop](https://desktop.github.com/) and sign in to your GitHub account.
2. Open Terminal, change into your actual project directory, and initialize Git:

   ```sh
   cd /absolute/path/to/triagedesk
   git init -b main
   ```

   Replace `/absolute/path/to/triagedesk` with the folder selected in step 1. If that folder is already a Git repository, skip initialization.

3. In GitHub Desktop, choose **File → Add Local Repository**, select the same project folder, and add it.
4. Inspect the **Changes** list. It should contain source, tests, documentation, screenshots, `.github/workflows/ci.yml`, `.env.example`, and `uv.lock`. Local `.env`, `.venv`, model files, and database dumps should be absent.
5. Enter the commit summary **Initial release of TriageDesk**, then click **Commit to main**. A commit records this version locally; it has not uploaded anything yet.
6. Click **Publish repository**. Set the name to `triagedesk`, or another name you prefer. An appropriate description is:

   > Human-reviewed GitHub issue triage with category suggestions, related-report search, audit history, and reproducible ML evaluation.

7. Choose visibility. Leave **Keep this code private** selected for a private repository; clear it if you intend to publish the code publicly. Click **Publish Repository**.
8. Choose **Repository → View on GitHub**. Confirm that the README appears on the repository landing page.

For this workflow, let GitHub Desktop create the remote repository. There is no need to create a separate empty one in the browser first.

Official guide: [Creating your first repository using GitHub Desktop](https://docs.github.com/en/desktop/overview/creating-your-first-repository-using-github-desktop).

## 3. Alternative: Terminal and an empty GitHub repository

Use this option instead of the Desktop publishing workflow.

### Create the empty remote repository

Open [GitHub's new repository page](https://github.com/new):

- Choose your own account as the owner.
- Name the repository `triagedesk`, or your preferred name.
- Choose public or private visibility.
- Leave initialization with a README, license, or `.gitignore` disabled. Those files already exist locally.
- Create the repository and copy its HTTPS URL.

### Initialize and review the files

Run from your actual project folder:

```sh
cd /absolute/path/to/triagedesk
git init -b main
git add .
git status --short
git diff --cached --stat
```

Skip `git init` if the local repository already exists. `git add .` prepares the non-ignored files for the next commit; `git status` and `git diff` let you inspect them before recording the version.

For an additional check:

```sh
git ls-files .env .venv artifacts data
git ls-files .env.example .github/workflows/ci.yml uv.lock README.md
```

The first command should print nothing. The second should list all four intended files. If unexpected local or sensitive files appear, remove them from staging before committing and inspect the ignore rules.

### Commit and push

```sh
git commit -m "Initial release of TriageDesk"
git remote add origin https://github.com/YOUR_USERNAME/triagedesk.git
git push -u origin main
```

Replace `YOUR_USERNAME` and the repository name with the values in the actual HTTPS URL. `origin` is the local nickname for the remote repository. `push` uploads commits; `-u` connects the local `main` branch to the remote branch for later pushes.

If Git reports that your identity is unknown, set your chosen author name and your verified or GitHub-provided no-reply email **for this repository**, then retry the commit:

```sh
git config user.name "Your Name"
git config user.email "YOUR_VERIFIED_OR_NOREPLY_EMAIL"
```

These are placeholders. Your GitHub account's email settings show the no-reply address if you prefer not to publish a personal address in commits.

### Authenticate

GitHub does not accept the account password for HTTPS Git operations. Use browser authentication through GitHub CLI, a supported credential manager, GitHub Desktop, or an already configured SSH setup.

If [GitHub CLI](https://cli.github.com/) is installed, browser authentication can be configured with:

```sh
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
```

Then retry `git push -u origin main`. If using a personal access token instead, enter it only in the authentication prompt or credential manager, not in code, a remote URL, screenshots, or chat. Pushing this project's workflow also requires authorization to create/update workflow files; follow the authentication error if your chosen credential lacks that permission.

Official references: [Adding locally hosted code](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github) and [command-line authentication](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github#authenticating-with-the-command-line).

## 4. Check the published repository

After publication:

1. Confirm that the README renders and the screenshots and documentation links work.
2. Confirm that `.github/workflows/ci.yml`, `.env.example`, `uv.lock`, tests, and the license are present.
3. Open the **Actions** tab and inspect the CI run triggered by the push. The project has a recorded local result of 46 passing tests; a remote success should only be claimed after that run actually passes. If Actions is disabled for the account or repository, enable it before expecting a run.
4. Add the description and, optionally, topics such as `python`, `fastapi`, `postgresql`, `streamlit`, `machine-learning`, `issue-triage`, and `docker`.
5. Keep the homepage field empty unless you have a real, verified hosted application URL. A GitHub source repository is not a deployed application.

## 5. Keep the real-data bundle separate

The source-only demo can run from a normal clone with Docker. The owner-provided `triagedesk-real-data.tar.gz` archive is approximately 101 MiB and is intentionally separate from source.

GitHub blocks files larger than 100 MiB in normal Git repositories. Keep the snapshot archive out of commits. If you later choose to distribute that data, use appropriate artifact storage or a separately reviewed release asset, retain attribution, and add its actual download instructions once available. The README currently claims no hosted download URL.

Official reference: [GitHub file-size limits and binary distribution](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github).

## 6. Publish later changes

In GitHub Desktop, review the changed files, enter a commit summary, commit, and choose **Push origin**.

For a README-only terminal update:

```sh
git add README.md
git diff --cached
git commit -m "Update project documentation"
git push
```

Select other changed paths deliberately when publishing code changes.

## Troubleshooting

| Message or symptom | What it usually means |
|---|---|
| `not a git repository` | Change into the project folder and initialize it, or add the correct repository to Desktop. |
| `Author identity unknown` | Configure your chosen name and verified/no-reply email locally, then retry the commit. |
| `remote origin already exists` | Inspect `git remote -v`; use the existing remote if correct. Do not add a second `origin`. |
| `Repository not found` | Check the owner/name in the remote URL and whether the authenticated account has access. |
| Authentication fails | Authenticate through Desktop/CLI or a supported credential manager; the account password is not a Git credential. |
| A workflow file is rejected | The chosen credential may lack authorization to update workflows; adjust the authentication rather than deleting the CI file. |
| Push is rejected because the remote has commits | The remote was initialized or changed independently. Inspect its history and integrate it deliberately; avoid force-pushing over existing work. |
| GitHub only shows a ZIP file | The archive was uploaded rather than its extracted source. Publish the project files at the repository root. |
| README images do not load | Ensure `docs/screenshots/` was committed along with the README. |
| Local `.env` appears in staged files | Stop before pushing; inspect staging and the ignore rules. `.gitignore` does not untrack files already committed. |
