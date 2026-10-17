#!/usr/bin/env bash
# Explicit operator action; never run this from a customer request or an agent plan.
set -euo pipefail
runtime_dir="${1:-/opt/nbppt-video-runtime}"
mkdir -p "$runtime_dir"
python3 -m venv "$runtime_dir/venv"
"$runtime_dir/venv/bin/pip" install --only-binary=:all: sherpa-onnx==1.13.8 numpy==2.5.4
archive="$runtime_dir/melo.tar.bz2"
curl -fL --max-time 300 -o "$archive" https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-melo-tts-zh_en.tar.bz2
python3 - "$archive" "$runtime_dir" <<'PY'
import hashlib, pathlib, sys, tarfile
archive, root = map(pathlib.Path, sys.argv[1:])
expected = 'e58351ed7149f290a54534538badd4077cdbe6fddc964b24d0bee870415d1514'
if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
    raise SystemExit('Model archive checksum mismatch; refusing installation')
with tarfile.open(archive) as bundle:
    bundle.extractall(root, filter='data')
model = root / 'vits-melo-tts-zh_en/model.onnx'
if hashlib.sha256(model.read_bytes()).hexdigest() != 'bf30582eb1b012250a35b1a4a80e7dfbcf8485e7bb9de0d95efbbeef0e4ad86d':
    raise SystemExit('Model checksum mismatch')
print('MeloTTS model verified. Preserve its bundled MIT LICENSE.')
PY
chmod -R a+rX "$runtime_dir/vits-melo-tts-zh_en"
printf 'Set NBPPT_TTS_PYTHON=%s/venv/bin/python\n' "$runtime_dir"
printf 'Set NBPPT_TTS_MODEL_DIR=%s/vits-melo-tts-zh_en\n' "$runtime_dir"
