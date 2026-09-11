# StorySprout

StorySprout creates personalized illustrated stories that help parents teach
young children everyday lessons. A parent describes what they want their
child to learn, and StorySprout builds a story around familiar characters,
the child's interests, and an age-appropriate lesson. Over time, it remembers
parent feedback and uses it to improve future stories.

The initial audience is parents of children ages **2–4**. The experience is
parent-led: the parent chooses the lesson, reads the story, and decides what
worked. The sections below describe the intended product; the current
implementation is a small command-line prototype.

## The end-to-end experience

1. **Set up a child profile.** Save the child's age, interests, favorite themes,
   and recurring characters. Reuse this context across books.
2. **Choose today's lesson.** Describe a situation such as taking turns,
   asking politely for help, or handling frustration. Choose an approximate
   read time of 2, 5, or 8 minutes and optionally enable rhyming. Additional
   controls for characters, setting, tone, and vocabulary sit behind More.
3. **Generate the complete storybook.** Produce age-appropriate text and one
   illustration per page, with consistent character appearances and personalities.
   An internal story outline guides generation; the parent does not need to
   approve a separate storyboard.
4. **Read together.** Display the book in a single scrolling view, with page
   text and pictures. The story introduces a situation, shows a problem and
   its consequences, and reaches a gentle resolution. A distinct
   **What we learned** section at the end reinforces the original lesson.
5. **Repair an individual page.** Accept natural-language feedback to change
   text, a picture, or both. Small edits affect only that page. For changes
   that affect later events, the intended experience offers the parent a
   choice to update subsequent pages for continuity.
6. **Remember what works.** Collect lightweight parent feedback on enjoyment,
   length, style, and whether the lesson seemed useful. Use remembered
   preferences as future defaults, while honoring explicit choices on the
   current request. Preserve character relationships and previous adventures
   so later books feel connected.

For example, a parent requests a rhyming story about taking turns, then says,
“Five minutes was too long. Default to two minutes next time, but keep the
rhyme.” On a later visit, a new story about asking for help uses those saved
preferences without the parent repeating them. This demonstrates remembered
preferences, rather than making a claim about measured child learning.

## Hackathon architecture: From Memory to Muscle Memory

StorySprout targets an agent workflow that improves across sessions through
both remembered knowledge and reuse of successful execution procedures.
The planned responsibilities are:

| Component | Intended role |
| --- | --- |
| RocketRide | Orchestrate context retrieval, model and image-service calls, page repair, and saving results. |
| Language and image models | Generate story text, illustration prompts, and images. |
| Cognee | Structure free-text feedback and story information into reusable knowledge. |
| HydraDB | Persist and retrieve child preferences, character relationships, and story history across sessions. |
| Hotdata | Query structured feedback, story history, and execution results to inform defaults and compare runs. |
| Modiqo / Rote | Capture successful procedures, such as page repair, and replay them with new inputs. |
| Application storage | Preserve finished books, image files or references, and original feedback. |
| Snyk | Scan the application during development and help address security findings. |

The generation flow is: **request → retrieve context → generate text and
illustrations → check the result → save and display the book**. The learning
loop is: **parent feedback → structured memory → durable storage → better
defaults for the next book**. Rote adds execution reuse; comparisons of actual
latency, model usage, retries, and outcomes will show whether reuse helps.

These are planned integrations, not completed capabilities. In particular,
the Cognee–HydraDB connection and Rote capture/replay need integration testing.
Local profile storage alone does not satisfy the full hackathon architecture.

## What works today

- `hello-world.pipe` and `hello_world.py`: a real RocketRide model-call smoke test.
- `story-generation.pipe` and `story-gen.py`: a simple age-aware prompt and
  plain-text response, with an optional question override.
- A saved local child age: initially 3, updated with `--age`, and reused on
  later runs from a Git-ignored JSON profile.
- An optional `--test-memory` follow-up that probes same-session model recall;
  this is separate from the script's explicit profile persistence.

The current pipeline is **webhook input → OpenAI model → answer output**.
It does not yet generate structured books or illustrations, provide a browser
reader or page editing, learn from parent feedback, or use the planned memory
and analytics services. The placeholder prompts are intentionally easy to replace.

Narration, animated page turns, quizzes, media recommendations, and advanced
learning analytics are outside the initial product scope.

## Setup

Use Python 3.10 or newer. Run these commands from this repository:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your RocketRide runtime endpoint, RocketRide API key, and
OpenAI API key. `.env` is ignored by Git. Do not put keys in the `.pipe` file.
The SDK substitutes its `${ROCKETRIDE_OPENAI_KEY}` placeholder at runtime.
Process environment variables take precedence over `.env` values.

The sample uses the documented `openai-4o-mini` profile. It requires OpenAI
API access and model credits as well as access to a RocketRide runtime.
Installing the Python SDK installs a client; it does not start a local engine.

### Which endpoint?

Use the runtime/API connection URI issued for your account. The
[Cloud SDK guide](https://cloud.rocketride.ai/sdk) uses
`https://api.rocketride.ai`, while the
[Python reference](https://docs.rocketride.org/develop/python/) uses
`https://cloud.rocketride.ai`. This project's hello-world test has successfully
used `https://staging.rocketride.ai` with a staging-issued key. Match the endpoint
to the environment where your key was created.
Use HTTPS/WSS for remote connections.

For a local engine that is already running, set `ROCKETRIDE_URI` to its
address (normally `ws://localhost:5565`) and use its configured authentication
key. The [quickstart](https://docs.rocketride.org/quickstart/) covers starting
the runtime through the IDE extension.

## Test

```sh
.venv/bin/python hello_world.py
```

Expected model answer:

```text
Hello from RocketRide!
```

The script connects to the engine, starts `hello-world.pipe`, sends a typed
question, prints the returned answer, and terminates the pipeline in a
`finally` block. You do not need to deploy the pipeline separately or open
a browser chat. An empty answer raises an error; a model may vary wording.

Try your first story:

```sh
.venv/bin/python hello_world.py 'Write a 150-word story for a three-year-old about taking turns. Use Clownfish and Squid. End with a separate What we learned moral.'
```

You can open `hello-world.pipe` in the RocketRide IDE extension to inspect
the same three-node pipeline visually.

## Saved child age

`story-gen.py` saves a single profile in `data/child-profile.json` (ignored by Git).
The first run defaults to age 3. Explicit `--age` values update the profile;
later runs reuse the saved age. The profile is saved before the model call,
so it survives a connection or generation failure.

```sh
.venv/bin/python story-gen.py          # Saved age, or 3 on the first run
.venv/bin/python story-gen.py --age 5  # Save and use age 5
.venv/bin/python story-gen.py          # Reuse age 5
```

This is local application persistence: the script supplies the saved age as
context on each generation request. `--test-memory` still checks the model's
same-session recall without supplying age in the follow-up; it is a separate
test from saved-profile persistence. No database integration is added yet.

## Troubleshooting

- Connection failure: check the runtime URI and whether the engine is running.
- Authentication failure: verify the RocketRide key belongs to that endpoint.
- Model authentication, quota, or access failure: check the separate OpenAI key,
  available credits, and access to the selected model profile.
- Unknown node/profile: inspect the target runtime's available providers. This
  sample follows the current Cloud SDK example; a staging runtime may differ.
- Empty answer: inspect the model call and the `questions`/`answers` lane wiring.

## Verification status

The hello-world pipeline has been verified against RocketRide staging and
returned `Hello from RocketRide!` using a real model call. Local checks also
cover SDK compatibility, pipeline wiring, and profile defaults, updates, and
persistence after a simulated model failure. The full product experience and
planned sponsor integrations are not yet implemented or verified.
