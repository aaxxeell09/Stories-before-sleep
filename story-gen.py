"""Send a simple age-aware prompt through the story-generation pipeline."""

import argparse
import asyncio
import json
import os
from pathlib import Path

from rocketride import RocketRideClient
from rocketride.schema import Question


ROOT = Path(__file__).resolve().parent
PROFILE_PATH = ROOT / "data" / "child-profile.json"
DEFAULT_QUESTION = "Say hello in one short sentence and explicitly mention the child's exact age in years."
MEMORY_QUESTION = "What is the child's exact age in years? If you don't know, say 'I don't know.' Do not guess."


def child_age(value: str) -> int:
    try:
        age = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Age must be a whole number.") from None
    if not 0 <= age <= 18:
        raise argparse.ArgumentTypeError("Age must be between 0 and 18.")
    return age


def save_child_age(age_override: int | None, path: Path = PROFILE_PATH) -> int:
    """Resolve and save one local child profile before making a model request."""
    profile = json.loads(path.read_text()) if path.exists() else {"id": "default", "age": 3}
    if not isinstance(profile, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    age = age_override if age_override is not None else profile.get("age", 3)
    if type(age) is not int or not 0 <= age <= 18:
        raise ValueError(f"Saved age in {path} must be a whole number between 0 and 18.")
    profile.setdefault("id", "default")
    profile["age"] = age
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2) + "\n")
    return age


async def ask(client: RocketRideClient, token: str, question: Question) -> None:
    response = await client.chat(token=token, question=question)
    answers = response.get("answers")
    if not isinstance(answers, list) or not answers:
        raise RuntimeError("RocketRide returned no answer.")
    if any(not isinstance(answer, str) or not answer.strip() for answer in answers):
        raise RuntimeError("RocketRide returned an unexpected response.")
    if any(answer.lstrip().startswith("**LLM error**") for answer in answers):
        raise RuntimeError("The model request failed. Check model access and API credits.")
    print("Response:", flush=True)
    print("\n".join(answers), flush=True)


async def generate(age: int, prompt: str, test_memory: bool = False) -> None:
    # RocketRide loads .env from the working directory.
    os.chdir(ROOT)
    question = Question()
    question.addInstruction("Response", "Reply in one short, age-appropriate sentence.")
    question.addContext(f"Child's age: {age} years old.")
    question.addQuestion(prompt)

    print(f"Child's age: {age}\nQuestion: {prompt}\n", flush=True)
    async with RocketRideClient(request_timeout=120_000) as client:
        started = await client.use(filepath=str(ROOT / "story-generation.pipe"))
        token = started["token"]
        try:
            await ask(client, token, question)
            if test_memory:
                # Fresh payload: no age context, history, or previous answer.
                follow_up = Question()
                follow_up.addQuestion(MEMORY_QUESTION)
                print(f"\nMemory check (same session; no age supplied):\n{MEMORY_QUESTION}", flush=True)
                await ask(client, token, follow_up)
        finally:
            await client.terminate(token)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--age", type=child_age, default=None, help="Save a new age; otherwise reuse the saved age (initial default: 3).")
    parser.add_argument("--question", default=DEFAULT_QUESTION, help="Override the placeholder question.")
    parser.add_argument("--test-memory", action="store_true", help="Ask for the age again in the same session without sending age or history.")
    args = parser.parse_args()
    if not args.question.strip():
        parser.error("Question cannot be empty.")
    try:
        age = save_child_age(args.age)
    except (ValueError, OSError) as exc:
        parser.error(f"Could not load/save child profile: {exc}")
    try:
        asyncio.run(generate(age, args.question.strip(), args.test_memory))
    except KeyboardInterrupt:
        raise SystemExit(130)


if __name__ == "__main__":
    main()
