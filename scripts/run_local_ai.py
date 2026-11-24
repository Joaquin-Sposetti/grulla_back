"""Serve the downloaded model on loopback only. Ctrl+C stops it."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AI = ROOT / 'instance' / 'ai'
server = AI / 'b12020' / 'llama-b12020' / 'llama-server'
model = AI / 'Qwen3-4B-Q4_K_M.gguf'
if not server.exists() or not model.exists():
    raise SystemExit('Primero ejecutá: .venv/bin/python scripts/setup_local_ai.py')
args = [str(server), '--model', str(model), '--alias', 'grulla-local', '--host', '127.0.0.1', '--port', '8081',
        '--ctx-size', '8192', '--parallel', '1', '--threads', '4', '--n-gpu-layers', '0',
        '--no-webui', '--log-disable']
os.execv(str(server), args)
