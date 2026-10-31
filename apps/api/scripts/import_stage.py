import argparse
import json
from pathlib import Path

from canonguard.plot.stage_loader import (
    discover_movies,
    load_movie_catalog,
    load_stage_movie,
    probe_movie,
)


def _default_corpus() -> Path:
    root = Path(__file__).resolve().parents[3]
    return root / "data" / "corpus" / "STAGE"


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect/probe a local STAGE benchmark copy.")
    parser.add_argument("--corpus", type=Path, default=_default_corpus())
    parser.add_argument("--movie", type=Path, help="Inspect a single movie directory.")
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Dump the observed file/field schema instead of loading PlotUnits.",
    )
    parser.add_argument("--limit", type=int, default=1)
    args = parser.parse_args()

    movies = (
        [(args.movie, "unknown")]
        if args.movie is not None
        else discover_movies(args.corpus)[: args.limit]
    )

    if not movies:
        print(
            json.dumps(
                {
                    "error": "no STAGE movies found",
                    "corpus": str(args.corpus),
                    "hint": "Place a local copy under data/corpus/STAGE/<Chinese|English>/<movie>/",
                },
                ensure_ascii=False,
            )
        )
        return

    if args.probe:
        print(
            json.dumps(
                [probe_movie(movie_dir) for movie_dir, _ in movies],
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    payload = []
    catalog = load_movie_catalog(args.corpus)
    for movie_dir, language in movies:
        movie = load_stage_movie(movie_dir, language, info=catalog.get(movie_dir.name))
        payload.append(
            {
                "movie_id": movie.movie_id,
                "title": movie.title,
                "language": movie.language,
                "genres": list(movie.genres),
                "scenes": len(movie.script_scenes),
                "episodes": len(movie.episodes),
                "relations": len(movie.relations),
                "characters": len(movie.characters),
                "has_causality_graph": movie.causality is not None,
                "episode_preview": [
                    {
                        "episode_id": episode.episode_id,
                        "summary": episode.summary,
                        "events": list(episode.event_texts),
                        "document_refs": list(episode.document_refs),
                        "narrative_function": episode.narrative_function,
                    }
                    for episode in movie.episodes[:3]
                ],
            }
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
