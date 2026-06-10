`./forgetool cluster genconfig` and `./clustertool-new genconfig` both run a decrypt pass before invoking talhelper. On success they re-encrypt at the end. **On failure, they leave every SOPS-managed file decrypted on disk** — cleartext sitting in the working tree until manually restored.

Hit during PR 5 of the secrets migration (2026-06-09): forgetool rejected Talos v1.13.4, leaving ~20 `.secret.yaml` files + `clusterenv.yaml` cleartext. Caught via `git status` showing them as modified, then `git diff` showing cleartext credentials in the `-` (HEAD) side and encrypted blobs in the `+` (working tree) side... wait, the other direction: cleartext on the working tree (current disk) side after the decrypt step.

**Why:** Why save this as feedback — this is a foot-gun in the local workflow. Decrypt-on-failure means a failed genconfig followed by an unrelated `git add -A` could commit cleartext credentials to git. The pre-commit hook (`forgetool checkcrypt`) catches some but not all of these (it caught `encryption-config.secret.yaml` once but not the other `.secret.yaml` files that already existed).

**How to apply:** After any failed genconfig:
1. **First**: `git status --short` — look for unexpected `M` lines on `clusterenv.yaml` and `.secret.yaml` files.
2. `git restore <each unintentionally-touched file>` — return them to encrypted state. Or `./forgetool encrypt` if intentional edits exist.
3. NEVER `git add -A` or `git commit -a` after a failed genconfig without first verifying restore.
4. If genconfig is itself blocked (talhelper version, missing env var), don't run it at all — work around with live JSON patches via `talosctl patch mc` instead.

Related: `forgetool-clustertool-split`, `forgetool-talos-apply-workflow`.
