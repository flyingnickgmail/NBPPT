#!/usr/bin/env bash
# Optional operator-run model install; never invoked by a generation request.
set -euo pipefail
runtime_dir="${1:-/opt/nbppt-video-runtime}"
mkdir -p "$runtime_dir"
archive="$runtime_dir/kokoro-v1_1.tar.bz2"
curl -fL --max-time 300 -o "$archive" https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/kokoro-multi-lang-v1_1.tar.bz2
python3 - "$archive" "$runtime_dir" <<'PY'
import hashlib, pathlib, sys, tarfile
archive, root = map(pathlib.Path, sys.argv[1:])
if hashlib.sha256(archive.read_bytes()).hexdigest() != 'a3f4c73d043860e3fd2e5b06f36795eb81de0fc8e8de6df703245edddd87dbad':
    raise SystemExit('Kokoro archive checksum mismatch')
destination = root / 'kokoro-multi-lang-v1_1'
if destination.exists():
    raise SystemExit('Existing model preserved; use a fresh runtime directory')
with tarfile.open(archive) as bundle:
    bundle.extractall(root, filter='data')
print('Kokoro model verified. Preserve bundled Apache-2.0 LICENSE.')
PY
printf 'Worker: NBPPT_KOKORO_MODEL_DIR=%s/kokoro-multi-lang-v1_1\n' "$runtime_dir"
printf 'Enable NBPPT_KOKORO_ENABLED=true on the gateway only after worker smoke validation.\n'
