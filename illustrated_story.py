"""Generate a story through RocketRide, then retrieve and save its page images."""

import argparse
import asyncio
import base64
import copy
import hashlib
import io
import json
import os
from contextlib import ExitStack
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageOps
from rocketride import RocketRideClient
from rocketride.schema import Question

from scripts.prepare_image_queries import build_image_queries
from scripts.rocketride_images import RocketRideImages


ROOT = Path(__file__).resolve().parent
NATIVE_SIZE = (1536, 1024)
FINAL_SIZE = (1440, 900)
IMAGE_MODEL = "gpt-image-1.5"


def save_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def make_story_prompt(request):
    prompt = json.loads((ROOT / "prompts/storybook.json").read_text())
    for key in ("child", "lesson", "preferences", "characters", "previous_context"):
        prompt[key] = copy.deepcopy(request[key])
    prompt["storybook_settings"].update(request["storybook_settings"])
    for key, expected in {"width_px": 1440, "height_px": 900, "aspect_ratio": "16:10", "orientation": "landscape"}.items():
        if prompt["storybook_settings"][key] != expected:
            raise ValueError(f"This pipeline requires storybook_settings.{key}={expected}")
    if type(prompt["child"]["age"]) is not int or prompt["child"]["age"] not in (2, 3, 4):
        raise ValueError("Child age must be 2, 3, or 4")
    if not isinstance(prompt["lesson"], str) or not prompt["lesson"].strip():
        raise ValueError("A lesson is required")
    if prompt["preferences"]["read_time_minutes"] not in (2, 5, 8):
        raise ValueError("Read time must be 2, 5, or 8 minutes")
    if type(prompt["preferences"]["rhyming"]) is not bool:
        raise ValueError("Rhyming must be a JSON boolean")
    for key in ("child", "lesson", "preferences", "characters", "previous_context", "storybook_settings"):
        if "{{" in json.dumps(prompt[key]):
            raise ValueError(f"Unfilled placeholder in {key}")
    return prompt


async def generate_story(client, prompt, response_path=None):
    question = Question(expectJson=True)
    question.addInstruction("Response", "Return the complete storybook package as valid JSON only. No markdown.")
    question.addQuestion(json.dumps(prompt, ensure_ascii=False))
    started = await client.use(filepath=str(ROOT / "illustrated-story.pipe"))
    token = started["token"]
    try:
        response = await client.chat(token=token, question=question)
        if response_path is not None:
            save_json(response_path, response)
        answers = response.get("answers")
        if not isinstance(answers, list) or len(answers) != 1:
            raise ValueError("RocketRide must return one complete JSON answer")
        if isinstance(answers[0], dict):
            return answers[0]
        if not isinstance(answers[0], str):
            raise ValueError("RocketRide returned an unexpected answer type")
        try:
            return json.loads(answers[0])
        except json.JSONDecodeError as exc:
            raise ValueError("Story response is invalid or truncated JSON; no images requested") from exc
    finally:
        await client.terminate(token)


def validate_book(book):
    if not isinstance(book, dict):
        raise ValueError("Story response must be a JSON object")
    for key in ("title", "full_story_text", "what_we_learned", "try_it_today"):
        if not isinstance(book["story"][key], str) or not book["story"][key].strip():
            raise ValueError(f"Missing story field: {key}")
    queries = build_image_queries(book)
    for query in queries:
        if "{{" in json.dumps(query):
            raise ValueError("Story response contains unfilled image placeholders")
        if query["page"]["narration"] is not None and not isinstance(query["page"]["narration"], str):
            raise ValueError("Narration must be text or null")
        for item in query["page"]["dialogue"]:
            if not all(isinstance(item[key], str) for key in ("speaker", "text")):
                raise ValueError("Dialogue must contain speaker and text strings")
    return queries


def native_prompt(query):
    # Keep the supplied template intact. Adapt the concrete image request to the
    # supported native size; the final 1440x900 copy is fitted locally afterward.
    def adapt(value):
        if isinstance(value, dict):
            return {k: adapt(v) for k, v in value.items()}
        if isinstance(value, list):
            return [adapt(v) for v in value]
        if isinstance(value, str):
            return value.replace("1440x900", "1536x1024").replace("16:10", "3:2")
        if type(value) is int:
            return {1440: 1536, 900: 1024}.get(value, value)
        return value
    result = copy.deepcopy(query)
    # Never change page text, character descriptions, or continuity data.
    for key in ("image_output", "composition", "instructions", "output_format"):
        result[key] = adapt(result[key])
    result["instructions"]["canvas_and_resolution"] = {
        key.replace("1440x900", "1536x1024"): value
        for key, value in result["instructions"]["canvas_and_resolution"].items()
    }
    return result


def save_image(data, native_path, final_path):
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        if image.format != "PNG" or image.size not in (NATIVE_SIZE, (1536, 960)):
            raise ValueError(f"Expected a {NATIVE_SIZE[0]}x{NATIVE_SIZE[1]} PNG, received {image.format} {image.size}")
        native_temporary = native_path.with_suffix(".tmp")
        native_temporary.write_bytes(data)
        native_temporary.replace(native_path)
        temporary = final_path.with_suffix(".tmp")
        ImageOps.pad(image, FINAL_SIZE, method=Image.Resampling.LANCZOS, color="white").save(temporary, format="PNG")
        temporary.replace(final_path)


async def generate_images(client, book, output, references, model=IMAGE_MODEL, quality="medium", max_pages=None):
    queries = validate_book(book)
    total_pages = len(queries)
    if max_pages is not None:
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        queries = queries[:max_pages]
    # Resolve IDs only through caller-supplied mappings, never model-chosen paths.
    for query in queries:
        for character in query["characters"]:
            ref = character.get("reference_image")
            if ref is not None and ref not in references:
                raise ValueError(f"No reference file supplied for image ID {ref!r}")
    images = output / "images"
    prompts = output / "image-queries"
    images.mkdir(exist_ok=True)
    prompts.mkdir(exist_ok=True)
    manifest = {"status": "generating", "story": "storybook.json", "total_story_pages": total_pages, "pages": []}
    save_json(output / "manifest.json", manifest)
    previous = None
    for number, query in enumerate(queries, 1):
        stem = f"page-{number:03d}"
        native_path = images / f"{stem}-native.png"
        final_path = images / f"{stem}.png"
        prompt = native_prompt(query)
        save_json(prompts / f"{stem}.json", prompt)
        try:
            if native_path.exists():
                # Resume from the retrieved original, also repairing a missing final copy.
                save_image(native_path.read_bytes(), native_path, final_path)
            else:
                kwargs = dict(model=model, prompt=json.dumps(prompt, ensure_ascii=False),
                              size="1536x1024", quality=quality, output_format="png", n=1)
                paths = []
                labels = []
                for character in query["characters"]:
                    ref = character.get("reference_image")
                    if ref is not None:
                        paths.append(references[ref])
                        labels.append(f"Image {len(paths)} is the identity reference for {character['name']}.")
                if previous:
                    paths.append(previous)
                    labels.append(f"Image {len(paths)} is the preceding page: use its visual continuity, not its text or scene.")
                print(f"Generating image {number}/{len(queries)}...", flush=True)
                with ExitStack() as stack:
                    if paths:
                        kwargs["prompt"] += "\n" + "\n".join(labels)
                        result = await client.images.edit(
                            image=[stack.enter_context(path.open("rb")) for path in paths], **kwargs)
                    else:
                        result = await client.images.generate(**kwargs)
                if not result.data or len(result.data) != 1 or not result.data[0].b64_json:
                    raise ValueError("Image API returned no image data")
                data = base64.b64decode(result.data[0].b64_json, validate=True)
                save_image(data, native_path, final_path)
            previous = native_path
            manifest["pages"].append({"page_number": number,
                "image": str(final_path.relative_to(output)),
                "native_image": str(native_path.relative_to(output)),
                "width_px": 1440, "height_px": 900})
            save_json(output / "manifest.json", manifest)
        except Exception as exc:
            manifest.update(status="failed", failed_page=number)
            if hasattr(exc, "diagnostic"):
                manifest["error"] = exc.diagnostic
            save_json(output / "manifest.json", manifest)
            raise
    manifest["status"] = "complete" if len(queries) == total_pages else "preview_complete"
    save_json(output / "manifest.json", manifest)
    return manifest


async def run(args):
    load_dotenv(Path.home() / ".hackathonenv", override=True)
    load_dotenv(ROOT / ".env")
    request = json.loads(args.request.read_text())
    prompt = make_story_prompt(request)
    references = {}
    if args.references:
        for ref, filename in json.loads(args.references.read_text()).items():
            path = (args.references.resolve().parent / filename).resolve()
            with Image.open(path) as image:
                image.verify()
            references[ref] = path
    image_key = os.getenv("OPENAI_API_KEY") or os.getenv("ROCKETRIDE_OPENAI_KEY")
    if not image_key:
        raise ValueError("Set OPENAI_API_KEY or ROCKETRIDE_OPENAI_KEY in ~/.hackathonenv or .env")
    output = args.output.resolve()
    config = {"request": request, "image_model": args.image_model, "quality": args.quality,
              "max_pages": getattr(args, "max_pages", None),
              "references": {key: {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                             for key, path in references.items()}}
    if args.resume:
        saved_config = json.loads((output / "run.json").read_text())
        saved_config.setdefault("max_pages", None)
        if saved_config != config:
            raise ValueError("Resume requires the same request, references, model and quality")
    else:
        output.mkdir(parents=True, exist_ok=False)
        save_json(output / "run.json", config)
    story_path = output / "storybook.json"
    if args.resume and story_path.exists():
        book = json.loads(story_path.read_text())
    else:
        save_json(output / "story-query.json", prompt)
        print("Generating story...", flush=True)
        async with RocketRideClient(request_timeout=600_000) as client:
            book = await generate_story(client, prompt, output / "story-response.json")
        validate_book(book)
        save_json(story_path, book)
    async with RocketRideClient(request_timeout=600_000) as client:
        started = await client.use(filepath=str(ROOT / "story-images.pipe"))
        token = started["token"]
        try:
            images = RocketRideImages(client, token, image_key)
            await generate_images(images, book, output, references, args.image_model, args.quality, getattr(args, "max_pages", None))
        finally:
            await client.terminate(token)
    print(f"Story and images saved: {output / 'manifest.json'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--references", type=Path, help="JSON map of reference IDs to local image paths")
    parser.add_argument("--image-model", default=IMAGE_MODEL)
    parser.add_argument("--quality", choices=("low", "medium", "high"), default="medium")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-pages", type=int, help="Generate only the first N page images for a preview")
    args = parser.parse_args()
    if args.max_pages is not None and args.max_pages < 1:
        parser.error("--max-pages must be positive")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        raise SystemExit(130)


if __name__ == "__main__":
    main()
