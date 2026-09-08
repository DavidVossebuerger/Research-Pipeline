# Scoring Prompts

Two prompts drive the pipeline's relevance judgments. Both expect JSON
output and use 0–10 scoring with German-language reasoning (swap to your
language by editing the files).

## Stage A — Abstract scoring (`prompts/abstract_score.txt`)

Runs on every fetched paper, in parallel, with a small fast model. Output
is clamped 0–10 and parsed with three fallback strategies (fenced
```json```, raw JSON, incremental scan).

```json
{
  "score": 8,
  "tags": ["market-microstructure", "orderbook"],
  "reason": "Direkt anwendbar auf HFT-Backtests mit replizierbarem Setup."
}
```

`score >= SCORE_STAGE_A_THRESHOLD` (default 7.0) qualifies for Stage B.

## Stage B — Deep scoring (`prompts/deep_score.txt`)

Runs on the top-K Stage A papers (default 10) after downloading the PDF
and extracting the first 4 KB of text. Output schema:

```json
{
  "overall_score": 7,
  "novelty": 6,
  "rigor": 8,
  "reproducibility": 5,
  "practical_value": 7,
  "summary": "Drei Sätze: Was das Paper macht, was es findet, was daran neu ist.",
  "why_interesting": "Ein Satz an einen Trader: warum relevant oder warum nicht.",
  "tags": ["factor-models", "cross-section"],
  "analysis": "4-8 Sätze Markdown: Problem & Beitrag (1-2 S), Methodik (1 S), Daten/Setup (1 S), Ergebnisse mit konkreten Zahlen falls vorhanden (1-2 S), Reproduzierbarkeit (1 S), Limitationen & Red Flags (1-2 S), praktische Anwendbarkeit (1 S)."
}
```

The `analysis` field is the bulk of what the daily-summary narrative uses
to connect papers.

## Customization

Edit the `.txt` files. Both use `str.format()` template variables:

| Prompt | Variables |
|---|---|
| `abstract_score.txt` | `{title}`, `{abstract}` |
| `deep_score.txt`    | `{title}`, `{abstract}`, `{pdf_text}` |

Constraints to keep when you customize:

1. **Always JSON.** Both prompts explicitly tell the model to respond
   with valid JSON only. The parser tolerates fenced code blocks and
   stray preamble, but other text hurts extraction reliability.
2. **Score field name matters.** Stage A expects `score`. Stage B expects
   `overall_score`. Renaming either will break parsing.
3. **Reasoning fields are German.** Switch to your language if you want;
   the parsing logic doesn't care about the language of string fields.
4. **Tag list is open vocabulary.** Use any tag string you like; the
   `daily_summary`, `weekly_digest`, and `autobuild` modules treat them as
   opaque tokens.

## Reliability Tips

- **Small models (< 4B params) often fail JSON extraction.** Use 7B+ for
  Stage A, and a frontier model via OpenRouter for Stage B if quality
  matters.
- **Long abstracts.** `arxiv` abstracts can be 2–3 KB; that fits the
  Stage A context window easily. No truncation needed.
- **PDF text is messy.** Equations, tables, and figures extract as
  garbage characters. The deep prompt accepts this — the model is told
  it's an excerpt, so it judges what's there rather than parsing
  perfectly.
- **Stage B truncates PDF text to 4 KB** (first chunk). Override via
  `extract_first_n_chars(pdf_path, n=8000)` if you have headroom.

## Testing Prompt Changes

After editing a prompt, run `tests/test_score.py` to confirm the parser
still handles the output. If you change the JSON schema, update the
tests accordingly.
