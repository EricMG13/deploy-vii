# Live batch schema-2026-10-22-r3 (schema-check)

- Command: schema-check (one strict response_format call per model and step; max_tokens 16, no reasoning parameter, nothing submitted)
- Steps: source_readiness, source_context, financials, narrative, readiness
- Cap: 0.10 USD; reserved 0, spent 0.0213625, remaining 0.0786375
- Catalog: `openrouter-models-2026-10-21.json`, the coordinator's saved models file (not in the repository; sha256 b17fc211fe65e4347e6808adbb2d35b4d2106aca90e690a81fcc5e66c6b89c9f), looked up 2026-10-22T07:58:39Z
- Accepted: 5; http_error: 0; other: 0; ineligible: 0; refused: 0
- Bisect: no
- Stopped: no

## Results

| Model | Step | Outcome | Class | HTTP | USD | Attempt | Sent schema sha256 | Relaxations | Keywords | Blocks later runs | Provider detail |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| openai/gpt-6.1-sol | source_readiness | accepted | truncated | 200 | 0.001852 | openai__gpt-6.1-sol-source_readiness-1 | 762998c99711498cf1f13a6342a233c0c72dc44b5e37cad6c7cad7f42c18ae06 | none | $defs, $ref, additionalProperties, anyOf, enum, items, minItems, properties, required, type; depth 6 (3 objects), 37 properties | - | - |
| openai/gpt-6.1-sol | source_context | accepted | truncated | 200 | 0.0033835 | openai__gpt-6.1-sol-source_context-1 | f96cc532eb796cfa61f6c1edfc972e8c1c103a8e3fe9a4c011953cb1fabc1434 | nullable-enum, const-to-enum, drop-length, nullable-array-anyof | $defs, $ref, additionalProperties, anyOf, enum, format, items, maxItems, minItems, pattern, properties, required, type; depth 9 (4 objects), 52 properties | - | - |
| openai/gpt-6.1-sol | financials | accepted | truncated | 200 | 0.013111 | openai__gpt-6.1-sol-financials-1 | 775b87aab382eee61981353bf0ff92969584dd323d7cd9a1bbf2891da71f5ed2 | nullable-enum, const-to-enum, drop-length, nullable-array-anyof | $defs, $ref, additionalProperties, anyOf, enum, exclusiveMaximum, exclusiveMinimum, format, items, maxItems, maximum, minItems, minimum, pattern, properties, required, type; depth 14 (7 objects), 232 properties | - | - |
| openai/gpt-6.1-sol | narrative | accepted | truncated | 200 | 0.002018 | openai__gpt-6.1-sol-narrative-1 | f26a2b3f10121ead358e8ab16e3802d748c810992a7cd98fe191efd7ab571f7d | const-to-enum, drop-length, nullable-array-anyof, oneof-anyof | $defs, $ref, additionalProperties, anyOf, enum, items, maxItems, minItems, pattern, properties, required, type; depth 8 (3 objects), 28 properties | - | - |
| openai/gpt-6.1-sol | readiness | accepted | truncated | 200 | 0.000998 | openai__gpt-6.1-sol-readiness-1 | b385bf970aa9c6e3b5f557f98645e23f6c14f4f44ee379c512f23ff0da444b57 | const-to-enum, drop-length, nullable-array-anyof | $defs, $ref, additionalProperties, anyOf, enum, items, minItems, pattern, properties, required, type; depth 10 (3 objects), 15 properties | - | - |

`Blocks later runs` `no: the 400 does not name the schema`: the provider gave no schema reason (Google's is only "Request contains an invalid argument"), so the cell stays eligible.
