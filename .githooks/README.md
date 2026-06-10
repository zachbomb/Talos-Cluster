# Git hooks

Versioned hooks for this repo. Git does not track `.git/hooks/`, so hooks live
here and are activated per-clone with one command:

```bash
git config core.hooksPath .githooks
```

Run that once after cloning. Verify with `git config --get core.hooksPath`
(should print `.githooks`).

## `pre-commit` — SOPS encryption guard

Blocks a commit if any **staged** file matching a `.sops.yaml` path rule
(`*.secret.yaml`, `*/values.yaml`, `clusterenv.yaml`, `talsecret.yaml`,
`clusters/main/talos/patches/*.secret.yaml`) is **not** SOPS-encrypted
(i.e. lacks an `ENC[AES256_GCM` marker). Passes cleanly when no secret file is
staged — so ordinary docs/manifest commits are never blocked.

### Why this replaced the old binary hook

The previous `.git/hooks/pre-commit` shelled out to the forgetool
`precommit` binary (`~/Library/Caches/forgetool/precommit`), which exited 1
with "no staged files to check" on **any** commit that staged no secret file —
forcing `git commit --no-verify` on every docs/manifest change.

`clustertool`'s `checkcrypt` is **not** a drop-in replacement: it scans the
whole working tree (no staged/exclude flag) and would fail on the intentionally
cleartext, gitignored `sops-age` bootstrap secret
(`clusters/main/kubernetes/flux-system/flux/sopssecret.secret.yaml`, which holds
the very age key that decrypts everything and therefore cannot be encrypted).

This self-contained shell hook depends on neither binary, checks only staged
files, and never sees gitignored files.

### Keep in sync

If `.sops.yaml` `creation_rules` change, update `secret_path_re` in
`pre-commit` to match.

### Bypass / restore

- One-off bypass (intentional): `git commit --no-verify`
- Restore the old forgetool binary hook (if its backup exists):
  `cp .git/hooks/pre-commit.forgetool.bak .git/hooks/pre-commit && git config --unset core.hooksPath`
