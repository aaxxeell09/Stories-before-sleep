# Cognee → RocketRide → HydraDB smoke test

`story-memory.py` runs a small, explicit sequence:

1. Call the native Cognee `recall` tool in `story-memory.pipe` through RocketRide's SDK.
2. Ask Cognee for the lesson and supporting quote using graph completion. This uses Cognee's configured model. With `--extractor openai`, instead send the retrieved chunks to `story-lesson.pipe` for one RocketRide OpenAI call.
3. Check that the quote occurs verbatim in the retrieved text, then call the native Hydra `store_memory` tool through RocketRide.
4. Query HydraDB independently and verify that the transfer marker is present.

Optional sample ingestion also calls Cognee directly through RocketRide, without a RocketRide model call, and checks processing status before continuing. The tool-host pipe contains an agent node that connects the tools, but this CLI does not ask that agent to plan calls. Live testing found the staging agent could answer without invoking tools; explicit calls avoid that failure and reduce model usage.

The default extractor makes no OpenAI calls through RocketRide. Cognee ingestion and graph completion can still use Cognee credits. The OpenAI extractor requires available quota on `ROCKETRIDE_OPENAI_KEY`.

Install the dependencies in your virtual environment:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Fill in the variables in `.env.example` in your local `.env`. `HYDRA_DB_TENANT_ID` holds the Hydra database name for this prototype. Keep `.env` private. The runner forwards the necessary credentials to RocketRide at execution time; the checked-in pipe contains placeholders only.

To seed a small sample in Cognee and run the transfer in a fresh pipeline session:

```sh
.venv/bin/python story-memory.py \
  --dataset storybook-transfer-demo \
  --seed-story examples/sharing-story.txt \
  --query 'Retrieve Pip and Luna Take Turns, story ID pip-and-luna-truck, with its lesson and source references.'
```

Once Cognee has processed the story, omit `--seed-story` to avoid ingesting it again. To use your own existing dataset:

```sh
.venv/bin/python story-memory.py \
  --dataset YOUR_DATASET \
  --query 'Find the story about sharing and return its lesson with supporting evidence.'
```

Each run uses a new Hydra collection named `story-transfer-…`, so readback cannot accidentally confirm an earlier run. Successful readback prints `VERIFIED` and saves a report in the ignored `data/` folder. These runs make real API calls and persist test data in both services; the script does not delete it.

An empty or unprocessed Cognee dataset cannot supply a story. Tool failures stop the transfer. If processing is still running or an API rate limit is reached, wait and retry without `--seed-story` after checking that the original ingestion succeeded. A write acknowledgment alone does not count as verified storage.

## Verified sample

The September 11, 2026 live test retrieved `Pip and Luna Take Turns` from Cognee dataset `storybook-transfer-demo`, saved it through RocketRide to Hydra database `default-tenant`, collection `story-transfer-9af608224a20`, and independently read back the exact transfer ID, lesson, and quote. The lesson was “taking turns lets everyone enjoy playing together.” The report is `data/story-transfer-9af608224a20.json` (local and ignored by Git).
