# -*- coding: utf-8 -*-
"""Recover known v9.4 PNGs when browser uploads flattened their directories.

Canonical files always win. Only the exact released image bytes are recovered;
this prevents a same-named exterior sprite from becoming an interior map.
"""
import hashlib
import os
from pathlib import Path
import tempfile

PIXEL_ASSET_HASHES = {
    "assets/scenes/cafe.png": "c26a75d11ba7391ce09521945a01a2a2777a3928cd142f512e5c90bb9ab7de4b",
    "assets/scenes/fish_market.png": "1302cb71e29ab521d0c7ec27ae76e1d34bf9fb98b188b9ee18ac2449aa83aa8e",
    "assets/scenes/general_store.png": "104782aff70c98c76bb6a8cee237b9b1628766e5af4421bcde23b3277f2a2e72",
    "assets/scenes/greenhouse.png": "3f69845a42e4d0b8fa6b243d9bfeb3361dc8b786aa0928e632017b5e8511a1e0",
    "assets/scenes/hall.png": "b0fe58e4ffdfd8ce02d622647503486178cac513d8185ec1456c0cb7bf347a0b",
    "assets/scenes/home.png": "319ef584cd4b62e81829d7c938de2660fd568a436aaa7b29c46df9a8002f60f3",
    "assets/scenes/mizuho.png": "c2be3622f44d0855640ecd809091e7119728602ee23fb7a146576a670bc1a383",
    "assets/scenes/shipping.png": "af07f48bc70b3d7f9809284f894659b510dc65a12ce65ad2ca1fe241f38edd79",
    "assets/scenes/shop.png": "ff70d8ae7585f525509b23e98b40221079fb39e2a49840fd0818e0f0543fe268",
    "assets/scenes/workshop.png": "33208de4ea5c436a010d064cd1b2fdad8022986a1d813959ac0bb630bca099e4",
    "assets/scenery/fish.png": "51268c1f07d710586f0ccd134268c02e51b04f681962fdb7a3dde22e79f802a1",
    "assets/scenery/props.png": "6006f2c8e87d96c8bcba82bc623d899fa493069aac6424eee18a65b48f799af0"
}


def restore_pixel_assets(root):
    """Atomically copy verified root PNGs into missing canonical asset paths."""
    root = Path(root)
    restored = []
    for relative, expected_digest in PIXEL_ASSET_HASHES.items():
        destination = root / relative
        if destination.is_file():
            continue
        filename = Path(relative)
        candidates = [root / filename.name]
        candidates.extend(sorted(root.glob(filename.stem + ' (*).png')))
        for source in candidates:
            if not source.is_file():
                continue
            payload = source.read_bytes()
            if hashlib.sha256(payload).hexdigest() != expected_digest:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=destination.parent,
                        prefix='.asset-recovery-', suffix='.tmp', delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(payload)
                os.replace(temporary, destination)
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()
            restored.append(relative)
            break
    return restored


def require_pixel_assets(root):
    """Prepare the same canonical paths that PyInstaller includes in the EXE."""
    root = Path(root)
    restored = restore_pixel_assets(root)
    missing = [relative for relative in PIXEL_ASSET_HASHES if not (root / relative).is_file()]
    if missing:
        raise RuntimeError('Missing pixel-art files:\n' + '\n'.join(missing))
    return restored


if __name__ == '__main__':
    base = Path(__file__).resolve().parent
    recovered = require_pixel_assets(base)
    print(f'Pixel asset layout ready: {len(PIXEL_ASSET_HASHES)}/12 images; '
          f'recovered {len(recovered)} flattened uploads.')
