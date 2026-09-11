"""Build ordered image follow-up prompts from a generated storybook JSON response."""

import argparse
import copy
import json
from pathlib import Path


TEMPLATE = Path(__file__).resolve().parents[1] / "prompts/storybook-image.json"


def build_image_queries(storybook):
    template = json.loads(TEMPLATE.read_text())
    pages = storybook["pages"]
    if not isinstance(pages, list) or not pages:
        raise ValueError("The storybook must contain a non-empty pages array")
    queries = []
    for number, page in enumerate(pages, start=1):
        if type(page["page_number"]) is not int or page["page_number"] != number:
            raise ValueError("Pages must be ordered sequentially starting at page 1")
        payload = page["image_generation_payload"]
        query = copy.deepcopy(template)
        # Page fields are authoritative: preserve text exactly, including nulls.
        query["page"] = {
            key: copy.deepcopy(page[key])
            for key in ("page_number", "image_description", "narration", "story_moment")
        }
        query["page"]["dialogue"] = [
            {"speaker": item["speaker"], "text": item["text"]}
            for item in page["dialogue"]
        ]
        query["characters"] = copy.deepcopy(payload["characters"])
        query["visual_continuity"] = copy.deepcopy(payload["visual_continuity"])
        query["style"]["illustration_style"] = storybook["visual_bible"]["illustration_style"]
        query["style"]["emotional_tone"] = payload["style"]["emotional_tone"]
        query["composition"]["primary_focus"] = payload["composition"]["primary_focus"]
        queries.append(query)
    return queries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("storybook", type=Path, help="Generated storybook response JSON")
    parser.add_argument("output", type=Path, help="New directory for the image queries")
    args = parser.parse_args()
    queries = build_image_queries(json.loads(args.storybook.read_text()))
    args.output.mkdir(parents=True, exist_ok=False)
    for number, query in enumerate(queries, start=1):
        path = args.output / f"page-{number:03d}.json"
        path.write_text(json.dumps(query, ensure_ascii=False, indent=2) + "\n")
    print(f"Prepared {len(queries)} image queries in {args.output}")


if __name__ == "__main__":
    main()
