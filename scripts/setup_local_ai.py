"""Download the CPU runtime and Apache-2.0 Qwen weights from their official repos."""
import hashlib
import json
import os
import platform
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'instance' / 'ai'
MODEL = 'Qwen3-4B-Q4_K_M.gguf'
MODEL_SHA = '7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5'
RUNTIME = 'b12020'


def file_digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def download(url, path, checksum):
    if path.exists() and file_digest(path) == checksum:
        print(path.name + ': verificado.', flush=True)
        return
    temporary = path.with_suffix('.download')
    digest = hashlib.sha256()
    print('Descargando ' + path.name + '…', flush=True)
    with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            digest.update(chunk)
    if digest.hexdigest() != checksum:
        temporary.unlink()
        raise SystemExit('Falló la verificación SHA-256 de ' + path.name)
    temporary.replace(path)
    print(path.name + ': descarga y SHA-256 correctos.', flush=True)


def main():
    if platform.system() != 'Darwin':
        raise SystemExit('Este instalador prepara macOS. Para Railway usá OpenRouter o instalá llama.cpp para Linux.')
    TARGET.mkdir(parents=True, exist_ok=True)
    arch = 'arm64' if platform.machine() == 'arm64' else 'x64'
    with urllib.request.urlopen(f'https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/{RUNTIME}', timeout=20) as response:
        release = json.load(response)
    name = f'llama-{RUNTIME}-bin-macos-{arch}.tar.gz'
    asset = next(a for a in release['assets'] if a['name'] == name)
    checksum = asset.get('digest', '').removeprefix('sha256:')
    if len(checksum) != 64:
        raise SystemExit('El release no ofrece un checksum verificable.')
    archive = TARGET / name
    download(asset['browser_download_url'], archive, checksum)
    runtime = TARGET / RUNTIME
    runtime.mkdir(exist_ok=True)
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            if not (runtime / member.name).resolve().is_relative_to(runtime.resolve()):
                raise SystemExit('El archivo contiene una ruta inesperada.')
            if member.issym() or member.islnk():
                if not (runtime / member.name).parent.joinpath(member.linkname).resolve().is_relative_to(runtime.resolve()):
                    raise SystemExit('El archivo contiene un enlace inesperado.')
        bundle.extractall(runtime)
    download('https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/' + MODEL, TARGET / MODEL, MODEL_SHA)
    print('Listo. Ejecutá: .venv/bin/python scripts/run_local_ai.py', flush=True)


if __name__ == '__main__':
    main()
