#!/usr/bin/env python3
"""Download and verify the pinned official Qwen3.6-35B-A3B snapshot."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import time
import requests

REPO = 'Qwen/Qwen3.6-35B-A3B'
REVISION = '995ad96eacd98c81ed38be0c5b274b04031597b0'
EXPECTED_BYTES = 71926865825

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--metadata-only', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        parser.error('--workers must be between 1 and 16')
    root = args.root.resolve()
    weights = root / 'weights'
    weights.mkdir(parents=True, exist_ok=True)
    response = requests.get(f'https://huggingface.co/api/models/{REPO}/revision/{REVISION}?blobs=true', timeout=60)
    response.raise_for_status()
    manifest = response.json()
    if manifest['sha'] != REVISION or len(manifest['siblings']) != 40 or sum(x['size'] for x in manifest['siblings']) != EXPECTED_BYTES:
        raise RuntimeError('Pinned 35B-A3B snapshot manifest does not match its inventory')
    (root / 'weight-manifest.json').write_text(json.dumps(manifest, indent=2))
    print(f'MANIFEST {REVISION} {len(manifest["siblings"])} files {EXPECTED_BYTES} bytes', flush=True)
    if args.metadata_only:
        return
    # An old success receipt must not survive a failed repeat verification.
    receipt = root / 'weights-verified.json'
    if receipt.exists():
        os.replace(receipt, root / 'weights-verified.previous.json')

    def get_file(item):
        name, size = item['rfilename'], item['size']
        target = weights / name
        if not target.resolve().is_relative_to(weights.resolve()):
            raise RuntimeError('Unsafe manifest path')
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + '.incomplete')
        expected = item.get('lfs', {}).get('sha256')
        candidate = target
        if not target.exists() or target.stat().st_size != size:
            candidate = partial
            for attempt in range(6):
                try:
                    offset = partial.stat().st_size if partial.exists() else 0
                    if offset > size:
                        raise RuntimeError(f'Oversized partial file: {partial}; inspect before repairing')
                    if offset == size:
                        break
                    headers = {'Range': f'bytes={offset}-'} if offset else {}
                    with requests.get(f'https://huggingface.co/{REPO}/resolve/{REVISION}/{name}', headers=headers, stream=True, timeout=(30, 120)) as result:
                        result.raise_for_status()
                        if offset and result.status_code == 206:
                            actual = result.headers.get('Content-Range', '').split(' ')[-1].split('-')[0]
                            if actual != str(offset):
                                raise RuntimeError('Unexpected Content-Range; partial file preserved')
                        elif offset:
                            offset = 0  # Server ignored Range: safely replace the partial byte stream.
                        with partial.open('ab' if offset else 'wb') as output:
                            for chunk in result.iter_content(8 * 1024 * 1024):
                                output.write(chunk)
                    if partial.stat().st_size != size:
                        raise RuntimeError(f'Incomplete size for {name}: {partial.stat().st_size}/{size}')
                    break
                except Exception as error:
                    print('RETRY', name, attempt + 1, type(error).__name__, flush=True)
                    if attempt == 5:
                        raise
                    time.sleep(3)
        digest = hashlib.sha256()
        with candidate.open('rb') as source:
            for chunk in iter(lambda: source.read(16 * 1024 * 1024), b''):
                digest.update(chunk)
        actual = digest.hexdigest()
        if expected and actual != expected:
            raise RuntimeError(f'SHA256 mismatch for {candidate}; do not deploy this snapshot')
        if candidate == partial:
            os.replace(partial, target)
        print('VERIFIED', name, size, actual, flush=True)
        return {'file': name, 'bytes': size, 'sha256': actual, 'published_sha256_checked': bool(expected)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        files = list(pool.map(get_file, manifest['siblings']))
    index = json.loads((weights / 'model.safetensors.index.json').read_text())
    if not all((weights / name).is_file() for name in set(index['weight_map'].values())):
        raise RuntimeError('Incomplete weight index')
    if list(weights.rglob('*.incomplete')):
        raise RuntimeError('Unfinished downloads remain')
    config = json.loads((weights / 'config.json').read_text())
    if config['architectures'] != ['Qwen3_5MoeForConditionalGeneration'] or config['text_config']['max_position_embeddings'] != 262144:
        raise RuntimeError('Unexpected 35B-A3B architecture or native context')
    result = {'revision': REVISION, 'files': files, 'total_bytes': sum(x['bytes'] for x in files), 'complete': True}
    temporary = root / 'weights-verified.json.tmp'
    temporary.write_text(json.dumps(result, indent=2))
    os.replace(temporary, receipt)
    print('COMPLETE', len(files), result['total_bytes'], flush=True)

if __name__ == '__main__':
    main()
