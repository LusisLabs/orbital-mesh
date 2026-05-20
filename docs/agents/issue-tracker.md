# Issue Tracker: GitHub

Issues and PRDs for this repo live in GitHub Issues for `LusisLabs/orbital-mesh`. Use the `gh` CLI for issue-tracker operations from the repo root.

## Repository

- GitHub remote: `https://github.com/LusisLabs/orbital-mesh.git`
- Local push policy: respect the root `AGENTS.md` no-mistakes workflow for publishing code changes. This file only defines issue-tracker behavior.

## Conventions

- Create an issue: `gh issue create --title "..." --body "..."`
- Read an issue: `gh issue view <number> --comments`
- List issues: `gh issue list --state open --json number,title,body,labels,comments`
- Comment on an issue: `gh issue comment <number> --body "..."`
- Apply labels: `gh issue edit <number> --add-label "..."`
- Remove labels: `gh issue edit <number> --remove-label "..."`
- Close an issue: `gh issue close <number> --comment "..."`

Infer the repository from the current checkout unless a task explicitly names a different repository.

## Skill Behavior

When a skill says "publish to the issue tracker", create a GitHub issue.

When a skill says "fetch the relevant ticket", run `gh issue view <number> --comments` and inspect labels plus recent comments before acting.
