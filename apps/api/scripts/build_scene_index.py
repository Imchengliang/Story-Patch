"""Build the raw scene index from STAGE scripts (local embeddings, zero LLM).

By default every discovered movie is indexed. Pass ``--limit``/``--per-language``
for a sample. Progress is checkpointed per movie into a sidecar file, so an
interrupted two-hour run resumes where it stopped instead of starting over.
"""

import argparse
import asyncio
import hashlib
import json
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from canonguard.plot.aliases import load_default_alias_table
from canonguard.plot.embedding import OllamaEmbedder, load_embedding_config
from canonguard.plot.scene_index import SceneIndex, SceneUnit, scenes_from_movie
from canonguard.plot.stage_loader import discover_movies, load_movie_catalog, load_stage_movie


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _pick_movies(
    movies: list[tuple[Path, str]], args: argparse.Namespace
) -> list[tuple[Path, str]]:
    if args.per_language:
        picked: list[tuple[Path, str]] = []
        for language in ("zh", "en"):
            picked.extend([item for item in movies if item[1] == language][: args.per_language])
        return picked
    if args.limit is not None:
        return movies[: args.limit]
    return movies


def _partial_path(output: Path, movies: list[tuple[Path, str]]) -> Path:
    """One checkpoint per movie selection, so sample and full runs never clash."""
    signature = hashlib.sha1(
        ",".join(sorted(path.name for path, _ in movies)).encode("utf-8")
    ).hexdigest()[:8]
    return output.with_name(f"{output.name}.{signature}.partial.jsonl")


def _load_partial(path: Path) -> tuple[list[SceneUnit], list[list[float]], set[str]]:
    units: list[SceneUnit] = []
    vectors: list[list[float]] = []
    done: set[str] = set()
    if not path.exists():
        return units, vectors, done
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                print(f"skip corrupt checkpoint line in {path}", file=sys.stderr)
                break
            movie_id = record["movie_id"]
            if movie_id in done:
                continue
            done.add(movie_id)
            units.extend(SceneUnit(**item) for item in record["units"])
            vectors.extend(record["vectors"])
    return units, vectors, done


def _write_partial(
    path: Path, movie_id: str, units: list[SceneUnit], vectors: list[list[float]]
) -> None:
    record = {
        "movie_id": movie_id,
        "units": [asdict(unit) for unit in units],
        "vectors": vectors,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()


async def run(args: argparse.Namespace) -> None:
    if args.output.exists() and not args.force:
        print(
            json.dumps(
                {
                    "skipped": True,
                    "reason": "index already exists; pass --force to rebuild",
                    "output": str(args.output),
                }
            )
        )
        return
    movies = _pick_movies(discover_movies(args.corpus), args)
    if not movies:
        print(json.dumps({"error": "no STAGE movies found", "corpus": str(args.corpus)}))
        return

    catalog = load_movie_catalog(args.corpus)
    aliases = load_default_alias_table()
    embedder = OllamaEmbedder(load_embedding_config())

    partial_path = _partial_path(args.output, movies)
    if args.force and partial_path.exists():
        partial_path.unlink()
    units, vectors, done = _load_partial(partial_path)
    todo = [(path, language) for path, language in movies if path.name not in done]
    if done:
        print(
            json.dumps(
                {
                    "resume": True,
                    "already_done": len(done & {path.name for path, _ in movies}),
                    "remaining": len(todo),
                    "checkpoint": str(partial_path),
                }
            ),
            file=sys.stderr,
            flush=True,
        )

    started = time.monotonic()
    for index, (path, language) in enumerate(todo, start=1):
        movie = load_stage_movie(path, language, info=catalog.get(path.name))
        movie_units = scenes_from_movie(movie, aliases)
        movie_vectors: list[list[float]] = []
        for start in range(0, len(movie_units), args.batch_size):
            batch = movie_units[start : start + args.batch_size]
            movie_vectors.extend(await embedder.embed([unit.embed_text() for unit in batch]))
        if len(movie_vectors) != len(movie_units):
            raise RuntimeError(
                f"{movie.movie_id}: embedded {len(movie_vectors)} vectors "
                f"for {len(movie_units)} scenes"
            )
        # Always checkpoint, even an empty movie, so resume never retries it.
        _write_partial(partial_path, movie.movie_id, movie_units, movie_vectors)
        units.extend(movie_units)
        vectors.extend(movie_vectors)
        elapsed = time.monotonic() - started
        print(
            json.dumps(
                {
                    "progress": f"{index}/{len(todo)}",
                    "movie": movie.title,
                    "language": language,
                    "scenes": len(movie_units),
                    "total_scenes": len(units),
                    "elapsed_s": round(elapsed, 1),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
            flush=True,
        )

    index = SceneIndex(units, vectors)
    index.save(args.output)
    if partial_path.exists():
        partial_path.unlink()

    languages = Counter(unit.language for unit in index.units)
    with_characters = sum(1 for unit in index.units if unit.characters)
    vector_path = args.output.with_name(f"{args.output.stem}.vectors.f32")
    print(
        json.dumps(
            {
                "movies": len({unit.work_id for unit in index.units}),
                "scenes": len(index),
                "embedding_dim": index.dim,
                "languages": dict(languages),
                "scenes_with_characters": with_characters,
                "output": str(args.output),
                "index_mb": round(args.output.stat().st_size / 1_048_576, 2),
                "vectors_mb": (
                    round(vector_path.stat().st_size / 1_048_576, 2)
                    if vector_path.exists()
                    else None
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a raw scene index from STAGE scripts.")
    parser.add_argument("--corpus", type=Path, default=_repo_root() / "data" / "corpus" / "STAGE")
    parser.add_argument(
        "--output",
        type=Path,
        default=_repo_root() / "data" / "indexes" / "scenes" / "index.json",
    )
    parser.add_argument("--limit", type=int, help="Take the first N movies (default: all).")
    parser.add_argument(
        "--per-language",
        type=int,
        help="Take N movies per language instead of --limit (keeps a sample bilingual).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore and delete the checkpoint, re-embedding every movie.",
    )
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
