# Upload AirGPT to a private GitHub repository

This folder is ready for a private GitHub upload. Local credentials, runtime `data/`, user-uploaded `drops/`, the downloaded Cloudflare binary, and heavyweight raw/export media are excluded by `.gitignore`. The small MP4/WebM walkthrough samples remain eligible to commit.

## 1. Review before staging

Git on this drive reports that the filesystem does not record ownership. Use the per-command safety override below; it does not change global Git configuration.

```powershell
cd D:\AirGPT
git -c safe.directory=D:/AirGPT status --short --untracked-files=all
```

Files that must never be pushed include `env.local`, `.env*` files containing values, `data/`, `drops/`, private keys/certificates, and any real customer or employee PII. `env.local.example` is safe only while all values remain blank or clearly fake.

## 2. Create the private repository

On GitHub, select **New repository**, name it `AirGPT`, set visibility to **Private**, and leave **Add a README**, `.gitignore`, and license unchecked. Copy the repository HTTPS URL.

GitHub CLI is not currently installed on this machine. If you later install it, the equivalent creation flow is:

```powershell
gh auth login
gh repo create AirGPT --private --source . --remote origin
```

Do not run the `gh repo create` command until the review and commit steps below are complete.

## 3. Stage, verify, and commit

```powershell
cd D:\AirGPT
git -c safe.directory=D:/AirGPT add .
git -c safe.directory=D:/AirGPT status --short
git -c safe.directory=D:/AirGPT diff --cached --stat
```

Confirm no credential file, runtime `data/`, user `drops/`, or unexpected large binary is staged. `third_party/colibri` is recorded as a submodule pointing to its public upstream repository, so Cloud agents can fetch it with `git submodule update --init --recursive`. Then commit the reviewed source, docs, and mock/debug assets:

```powershell
git -c safe.directory=D:/AirGPT commit -m "Add AirGPT source and mock/debug assets"
git -c safe.directory=D:/AirGPT branch -M main
```

## 4. Add the remote and push

Replace `YOUR_GITHUB_USER` with the repository owner:

```powershell
git -c safe.directory=D:/AirGPT remote add origin https://github.com/YOUR_GITHUB_USER/AirGPT.git
git -c safe.directory=D:/AirGPT remote -v
git -c safe.directory=D:/AirGPT push -u origin main
```

If `origin` already exists, inspect it with `remote -v`; do not add a duplicate or force-push.

## 5. Record with Cursor Cloud agents

1. Give Cursor access to the new private GitHub repository.
2. Start a Cloud agent from the repository, run `git submodule update --init --recursive`, and ask it to run AirGPT using mock fixtures only.
3. Ask it to record the browser walkthrough and save small review clips under `video-assets/03-demo-clips/<feature>/`.
4. Have the agent commit to a branch and open a pull request; review the clip and changed files before merging.
5. Keep real user data and credentials outside Git. Use Git LFS or release/object storage for large production masters.

Cloud agents can clone and record only after the remote exists and the initial commit has been pushed.

