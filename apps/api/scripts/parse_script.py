import argparse
import json
from pathlib import Path

from canonguard.plot.script_parser import parse_script


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse a screenplay text into scenes.")
    parser.add_argument("--file", type=Path, required=True)
    args = parser.parse_args()

    scenes = parse_script(args.file.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "scenes": [
                    {
                        "order": scene.order,
                        "heading": scene.heading,
                        "elements": [
                            {
                                "kind": element.kind,
                                "speaker": element.speaker,
                                "text": element.text,
                            }
                            for element in scene.elements
                        ],
                    }
                    for scene in scenes
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
