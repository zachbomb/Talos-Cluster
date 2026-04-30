# GoodMem (memory / RAG infrastructure)

Self-hosted [GoodMem](https://github.com/PAIR-Systems-Inc) server backing the Ollama
RAG project + Triparr-bot persistent memory.

- Image: `ghcr.io/pair-systems-inc/goodmem/server:latest`
- Database: CNPG cluster `goodmem-db` with pgvector extension
- Storage: 10Gi Longhorn (PostgreSQL data)
- Endpoint (REST): `https://goodmem.${BASE_DOMAIN}` via Traefik + cert-manager
- Endpoint (gRPC): cluster-internal at `goodmem.goodmem.svc.cluster.local:9090`
  (no external ingress yet — add a TraefikIngressRoute or LoadBalancer if needed)

## Bootstrap (one-time, after first successful deploy)

GoodMem's `init` flow creates the **root user** and **master API key**. This is
manual because the API key is generated only once.

```bash
# 1. Wait for the goodmem pod to be ready
kubectl rollout status -n goodmem deployment/goodmem

# 2. Run goodmem init from inside the pod (or from a CLI install pointing at the ingress)
#    The CLI is published at https://goodmem.ai/docs/cli
goodmem init --server https://goodmem.${BASE_DOMAIN} --save-config=false

# 3. Capture the printed API key (starts with gm_) and save into clusterenv:
sops clusters/main/clusterenv.yaml
# add: GOODMEM_API_KEY: gm_<your_key_here>

# 4. Configure the goodmem MCP plugin (in any Claude Code session):
#    /goodmem:configure   →  base_url=https://goodmem.${BASE_DOMAIN}, api_key=$GOODMEM_API_KEY
```

## Configure embedder (after bootstrap)

GoodMem doesn't include an embedding model — it calls one via API. Point it at
your local Ollama with `nomic-embed-text` to keep RAG embeddings on-prem:

```bash
# Via MCP (after configuring the plugin):
mcp__plugin_goodmem_goodmem__goodmem_embedders_create \
  name="ollama-nomic-embed" \
  provider_type="ollama" \
  base_url="http://192.168.10.202:11434" \
  model="nomic-embed-text" \
  dimensions=768
```

## Network access

- Pod uses CNPG database `goodmem-db-rw.goodmem.svc.cluster.local:5432`
- DB credentials auto-injected from `goodmem-db-app` secret (CNPG-managed)
- HTTP/REST: TLS terminated at Traefik (websecure entrypoint, secure-chain middleware)
- TLS *inside* the pod is disabled (`GOODMEM_TLS_DISABLED=true`) since the edge handles it

## Recovery / rebuild

PostgreSQL backups go to MinIO at `s3://cnpg-goodmem/` (Barman, daily 03:00, 30d retention).
Restore via standard CNPG procedure if needed.

## Open follow-ups

- [ ] Add a NetworkPolicy under `core/network-policies/` matching the repo pattern
- [ ] Decide whether to expose gRPC externally (only needed if remote agents talk to it)
- [ ] Add Homepage widget config once API endpoint stabilizes
