from hashlib import sha256
import os


HASH_CHUNK_SIZE = 1024 * 1024


def sha256_file(path):
    digest = sha256()
    with open(path, 'rb') as handle:
        while True:
            chunk = handle.read(HASH_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def document_hash_summary(**paths):
    parts = []
    for label, path in paths.items():
        if not path or not os.path.exists(path):
            parts.append(f"{label}=yok")
            continue
        try:
            parts.append(f"{label}_path={path}")
            parts.append(f"{label}_sha256={sha256_file(path)}")
        except Exception as exc:
            parts.append(f"{label}_hash_hata={exc}")
    return ", ".join(parts)
