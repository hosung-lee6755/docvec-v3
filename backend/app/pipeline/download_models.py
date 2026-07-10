"""One-time model warm-up: downloads every curated embedding model into the
shared HF cache volume so worker tasks never hit the network at request time.

Run inside the worker container:
    poetry run python -m app.pipeline.download_models
"""

from app.services.embedding import EMBEDDING_MODEL_REGISTRY, get_embedding_provider

_DOWNLOADABLE_BACKENDS = {"flag_embedding", "sentence_transformers"}


def main() -> None:
    for key, spec in EMBEDDING_MODEL_REGISTRY.items():
        if spec["backend"] not in _DOWNLOADABLE_BACKENDS:
            continue
        print(f"[download_models] {key} ({spec['repo_id']}) ...", flush=True)
        provider = get_embedding_provider(key)
        print(f"[download_models] {key} ready (dim={provider.dimension})", flush=True)


if __name__ == "__main__":
    main()
