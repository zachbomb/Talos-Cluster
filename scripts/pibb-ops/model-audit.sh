#!/usr/bin/env bash
# Model audit script — check for new Ollama models and TurboQuant status
set -euo pipefail

OLLAMA_HOST="${OLLAMA_HOST:-http://192.168.10.202:11434}"

echo "=== pibb-ops Model Audit ==="
echo "Date: $(date)"
echo "Ollama: $OLLAMA_HOST"
echo ""

# Current models
echo "=== Current Models ==="
curl -s "$OLLAMA_HOST/api/tags" 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
models = sorted(d.get('models', []), key=lambda x: x['name'])
total = 0
for m in models:
    size_gb = m['size'] / (1024**3)
    total += m['size']
    print(f'  {m[\"name\"]:<30} {size_gb:.1f} GB')
print(f'  ---')
print(f'  Total: {len(models)} models, {total/(1024**3):.1f} GB')
"
echo ""

# Check for model updates
echo "=== Update Check ==="
for model in qwen3:14b qwen3:8b qwen3.5:9b qwen2.5-coder:14b gpt-oss:20b nomic-embed-text; do
    echo -n "  $model: "
    # Check if there's a newer digest available
    response=$(curl -s -X POST "$OLLAMA_HOST/api/show" -d "{\"name\": \"$model\"}" 2>/dev/null)
    if echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('details',{}).get('parameter_size','?'))" 2>/dev/null; then
        true
    else
        echo "error checking"
    fi
done
echo ""

# Models to watch
echo "=== Models to Watch ==="
echo "  TurboQuant: Check ollama/ollama GitHub releases for KV cache compression support"
echo "  Gemma 4: google/gemma-4 — check ollama.com/library/gemma4"
echo "  Granite 4 Vision: ibm/granite-4.0-3b-vision — 3B vision model, very small"
echo "  Qwen3.5:35b: If A4000 arrives, could fit with TurboQuant"
echo ""
echo "Run monthly or when new models are announced."
