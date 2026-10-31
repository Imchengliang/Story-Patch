import argparse
import json
from pathlib import Path

from canonguard.plot.feedback import (
    SuggestionFeedback,
    append_feedback,
    load_feedback,
    suggestion_id_for,
    summarize_feedback,
)
from canonguard.plot.schemas import PlotSuggestion


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_suggestion(path: Path, index: int) -> tuple[dict[str, object], PlotSuggestion]:
    text = path.read_text(encoding="utf-8")
    start = text.find("{")
    if start < 0:
        raise SystemExit(f"no JSON object found in {path}")
    payload = json.loads(text[start:])
    items = payload.get("suggestions", [])
    if not items:
        raise SystemExit("no suggestions in payload")
    item = items[index - 1]
    return payload, PlotSuggestion.model_validate(item)


def main() -> None:
    parser = argparse.ArgumentParser(description="Record suggestion feedback.")
    parser.add_argument(
        "--store",
        type=Path,
        default=_repo_root() / "data" / "evaluations" / "suggestion_feedback.jsonl",
    )
    parser.add_argument("--suggestions-json", type=Path)
    parser.add_argument("--index", type=int, default=1, help="1-based suggestion index.")
    parser.add_argument("--suggestion-id")
    parser.add_argument("--corpus-reference", default="")
    parser.add_argument("--next-node", default="")
    parser.add_argument("--decision", choices=["adopt", "modify", "reject"])
    parser.add_argument(
        "--reason",
        default="other",
        choices=[
            "structure_mismatch",
            "character_mismatch",
            "world_conflict",
            "cliche",
            "low_novelty",
            "other",
        ],
    )
    parser.add_argument("--note", default="")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    if not args.report:
        if args.suggestions_json is not None:
            payload, suggestion = _load_suggestion(args.suggestions_json, args.index)
            stuck = payload.get("stuck_point", {})
            stuck_question = str(stuck.get("stuck_question", ""))
            feedback = SuggestionFeedback(
                suggestion_id=suggestion_id_for(suggestion),
                decision=args.decision,  # type: ignore[arg-type]
                reason_code=args.reason,  # type: ignore[arg-type]
                note=args.note,
                stuck_question=stuck_question,
                corpus_reference=suggestion.corpus_reference,
                next_node=suggestion.next_node,
            )
        else:
            if not (args.suggestion_id and args.decision):
                raise SystemExit("provide --suggestion-id and --decision, or --suggestions-json")
            feedback = SuggestionFeedback(
                suggestion_id=args.suggestion_id,
                decision=args.decision,  # type: ignore[arg-type]
                reason_code=args.reason,  # type: ignore[arg-type]
                note=args.note,
                corpus_reference=args.corpus_reference,
                next_node=args.next_node,
            )
        append_feedback(args.store, feedback)

    records = load_feedback(args.store)
    print(json.dumps(summarize_feedback(records), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
