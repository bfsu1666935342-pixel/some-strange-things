---
name: github-skill-sync
description: Publish or update a local Codex Skill in a GitHub repository. Use when the user asks to upload, publish, back up, or synchronize a Skill folder to GitHub; do not use for installing a Skill from GitHub.
---

# GitHub Skill Sync

Safely publish one local Skill or update its copy in an existing GitHub repository. Preserve the source Skill unless the user explicitly asks to move or reorganize it.

## Resolve the request

Identify:

- the source Skill directory, which must contain `SKILL.md`;
- the destination repository and destination path;
- whether this is a standalone repository or a collection of Skills;
- the intended branch and, for a new repository, its owner, name, and visibility.

Use explicit user choices first, then existing repository conventions. A standalone repository normally stores `SKILL.md` at its root. A collection should preserve its established layout; if none exists, use `skills/<skill-name>/`.

Ask one concise question only when a required choice cannot be inferred. In particular, do not guess the owner or public/private visibility of a new GitHub repository.

## Preflight

1. Resolve all paths to explicit absolute paths. Verify that the source contains `SKILL.md` and that its frontmatter `name` matches the directory name unless the repository deliberately uses another layout.
2. If the Skill Creator validator is available, run `quick_validate.py` against the source Skill.
3. Run `scripts/preflight.py <source-skill-dir>`. Stop if it reports a blocked file or possible secret. Report only filenames and finding categories; never print credential values.
4. Inspect repository state with `git status --short`, `git branch --show-current`, `git remote -v`, and the relevant diff. Preserve unrelated local changes.
5. Check GitHub authentication with `gh auth status` before any GitHub mutation. If `gh` is unavailable, use ordinary Git only when a working authenticated remote already exists; otherwise explain the missing prerequisite.

Do not publish `.env` files, credentials, private keys, caches, OS metadata, dependency directories, build output, or unrelated generated artifacts. Add narrowly scoped ignore rules when appropriate. Do not rewrite history, force-push, delete a repository, or change repository visibility unless the user explicitly requests it.

## Choose the sync mode

### Existing repository containing the Skill

Work in that repository. Update only the requested Skill files, review the diff, validate again, commit with a focused message, and push the current branch. If the user asks for a pull request, create a branch, push it, create the PR, and return its URL.

### Existing collection repository elsewhere

Clone or use the destination repository, then copy the source Skill into its exact destination folder. For an exact mirror, preview file additions, changes, and removals before applying them. Limit removals to the resolved destination Skill folder and never delete repository-wide files. Review the Git diff before committing.

### New standalone repository

Prefer a durable working copy outside the installed Skill directory unless the user explicitly wants the Skill directory itself to become a Git repository. Copy only the validated Skill contents, initialize the default branch as `main`, create a first commit, and create/push the GitHub repository with the requested visibility.

Typical command shape after all values are resolved:

```bash
git init -b main
git add --all
git diff --cached --check
git commit -m "Add <skill-name> skill"
gh repo create <owner>/<repo> --private --source . --remote origin --push
```

Replace `--private` only with the user's chosen visibility. Never interpolate an unverified repository name or path into a destructive command.

## Commit and verify

Before committing:

- inspect `git diff --cached --stat` and `git diff --cached`;
- confirm that every staged file belongs to the requested Skill change;
- rerun validation on the destination copy;
- use `git diff --cached --check` to catch whitespace errors.

After pushing, verify:

```bash
git status --short
git rev-parse HEAD
git ls-remote origin HEAD
```

If a pull request was created, verify its state with `gh pr view`. Return the repository or PR URL, branch, commit SHA, destination path, and any files intentionally excluded. If the push fails, keep the local commit intact and report the exact recovery step without repeatedly retrying authentication or destructive operations.

## Teaching-only requests

When the user asks only how to synchronize a Skill, explain the applicable mode and commands without creating repositories, committing, or pushing. Distinguish local Git steps from the GitHub-changing step so the user knows exactly when remote state changes.
