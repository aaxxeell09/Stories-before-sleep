"""Run the hello-world pipeline against a configured RocketRide engine."""

import argparse
import asyncio
import json
import os
from pathlib import Path

from rocketride import RocketRideClient
from rocketride.schema import Question


ROOT = Path(__file__).resolve().parent
DEFAULT_PROMPT = "Reply with exactly: Hello from RocketRide!"


async def run(prompt: str) -> None:
    # The SDK reads .env from the working directory. Keep it next to this script.
    os.chdir(ROOT)
    client = RocketRideClient(request_timeout=120_000)
    print("Connecting to RocketRide...", flush=True)
    async with client:
        print("Starting hello-world.pipe...", flush=True)
        started = await client.use(filepath=str(ROOT / "hello-world.pipe"))
        token = started["token"]
        try:
            question = Question()
            question.addQuestion(prompt)
            response = await client.chat(token=token, question=question)
            answers = response.get("answers")
            if not answers or not any(str(answer).strip() for answer in answers):
                raise RuntimeError("No answer returned. Check the model and output nodes in RocketRide.")
            for answer in answers:
                print(answer if isinstance(answer, str) else json.dumps(answer, indent=2))
        finally:
            await client.terminate(token)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="?", default=DEFAULT_PROMPT)
    args = parser.parse_args()
    try:
        asyncio.run(run(args.prompt))
    except KeyboardInterrupt:
        raise SystemExit(130)
