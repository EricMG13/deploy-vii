# Live batch schema-2026-10-22-bisect (schema-check)

- Command: schema-check (one strict response_format call per model and step; max_tokens 16, no reasoning parameter, nothing submitted)
- Steps: source_context, financials, narrative, readiness
- Cap: 0.30 USD; reserved 0, spent 0.016394, remaining 0.283606
- Catalog: `openrouter-models-2026-10-21.json`, the coordinator's saved models file (not in the repository; sha256 b17fc211fe65e4347e6808adbb2d35b4d2106aca90e690a81fcc5e66c6b89c9f), looked up 2026-10-22T06:26:14Z
- Accepted: 1; http_error: 7; other: 0; ineligible: 0; refused: 0
- Bisect: yes (variants are reported only; no real run sends them)
- Stopped: no

## Results

| Model | Step | Outcome | Class | HTTP | USD | Attempt | Sent schema sha256 | Relaxations | Keywords | Blocks later runs | Provider detail |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| openai/gpt-6.1-sol | source_context | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-source_context-1 | 75eb31361020ae3529cf52488b31297bb2fbc4f0db73db0fb1890c89ba8335eb | nullable-enum, const-to-enum, drop-length | $defs, $ref, additionalProperties, anyOf, enum, format, items, maxItems, minItems, pattern, properties, required, type | yes: schema rejection | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'source_context'. Please ensure it is a valid JSON Schema. |
| openai/gpt-6.1-sol | financials | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-financials-1 | ccf6aab259df5c487bb2aaa3223c31ecee546cc9405908822449387303bf8f33 | nullable-enum, const-to-enum, drop-length | $defs, $ref, additionalProperties, anyOf, enum, exclusiveMaximum, exclusiveMinimum, format, items, maxItems, maximum, minItems, minimum, pattern, properties, required, type | yes: schema rejection | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'financials'. Please ensure it is a valid JSON Schema. |
| openai/gpt-6.1-sol | narrative | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-narrative-1 | 58e27e482b6078d7bc09217565c09151913b2aa48bfc297bf6b0b96260881b42 | const-to-enum, drop-length | $defs, $ref, additionalProperties, anyOf, discriminator, enum, items, maxItems, minItems, oneOf, pattern, properties, required, type | yes: schema rejection | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'narrative': In context=('properties', 'rationale', 'items'), 'oneOf' is not permitted. |
| openai/gpt-6.1-sol | readiness | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-readiness-1 | 6efd5a9f971a84a91276f483ed097310f370c390753abda78c619f269cee328b | const-to-enum, drop-length | $defs, $ref, additionalProperties, anyOf, enum, items, minItems, pattern, properties, required, type | yes: schema rejection | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'readiness'. Please ensure it is a valid JSON Schema. |
| google/gemini-4-argon | source_context | http_error | http_error | 400 | 0 | google__gemini-4-argon-source_context-1 | 75eb31361020ae3529cf52488b31297bb2fbc4f0db73db0fb1890c89ba8335eb | nullable-enum, const-to-enum, drop-length | $defs, $ref, additionalProperties, anyOf, enum, format, items, maxItems, minItems, pattern, properties, required, type | no: the 400 does not name the schema | HTTP 400: Provider returned error; Google 400: Request contains an invalid argument. |
| google/gemini-4-argon | financials | http_error | http_error | 400 | 0 | google__gemini-4-argon-financials-1 | ccf6aab259df5c487bb2aaa3223c31ecee546cc9405908822449387303bf8f33 | nullable-enum, const-to-enum, drop-length | $defs, $ref, additionalProperties, anyOf, enum, exclusiveMaximum, exclusiveMinimum, format, items, maxItems, maximum, minItems, minimum, pattern, properties, required, type | no: the 400 does not name the schema | HTTP 400: Provider returned error; Google 400: Request contains an invalid argument. |
| google/gemini-4-argon | narrative | http_error | http_error | 400 | 0 | google__gemini-4-argon-narrative-1 | 58e27e482b6078d7bc09217565c09151913b2aa48bfc297bf6b0b96260881b42 | const-to-enum, drop-length | $defs, $ref, additionalProperties, anyOf, discriminator, enum, items, maxItems, minItems, oneOf, pattern, properties, required, type | no: the 400 does not name the schema | HTTP 400: Provider returned error; Google 400: Request contains an invalid argument. |
| google/gemini-4-argon | readiness | accepted | truncated | 200 | 0.002042 | google__gemini-4-argon-readiness-1 | 6efd5a9f971a84a91276f483ed097310f370c390753abda78c619f269cee328b | const-to-enum, drop-length | $defs, $ref, additionalProperties, anyOf, enum, items, minItems, pattern, properties, required, type | - | - |

`Blocks later runs` `no: the 400 does not name the schema`: the provider gave no schema reason (Google's is only "Request contains an invalid argument"), so the cell stays eligible.

## Bisect

| Model | Step | Variant | Outcome | Class | HTTP | USD | Attempt | Variant schema sha256 | Provider detail |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| openai/gpt-6.1-sol | source_context | one-of-to-any-of | not applicable | not sent | - | 0 | none | - | - |
| openai/gpt-6.1-sol | source_context | drop-format | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-source_context-drop-format-1 | 146954989c7c6356e405205e1f61a9285d6b3b79471dfff5ec30e8183c44b49d | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'source_context'. Please ensure it is a valid JSON Schema. |
| openai/gpt-6.1-sol | source_context | drop-pattern | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-source_context-drop-pattern-1 | d428f3317853ff188aa9758656e8ebb0ce56a3f8c8f2c52e7cf47f8283d6a011 | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'source_context'. Please ensure it is a valid JSON Schema. |
| openai/gpt-6.1-sol | source_context | drop-items-bounds | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-source_context-drop-items-bounds-1 | f3b38e7e30e26b723fe63b29b3b9c77af8d22076b7968f75da184f45cb708995 | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'source_context'. Please ensure it is a valid JSON Schema. |
| openai/gpt-6.1-sol | source_context | open-object | not applicable | not sent | - | 0 | none | - | - |
| openai/gpt-6.1-sol | source_context | any-of-null-to-type-union | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-source_context-any-of-null-to-type-union-1 | f317ec127ba13daba36671541f16796883845d8eb9f9fc6b1632ff33c289bb9f | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'source_context'. Please ensure it is a valid JSON Schema. |
| openai/gpt-6.1-sol | source_context | split-mixed-types | not applicable | not sent | - | 0 | none | - | - |
| openai/gpt-6.1-sol | source_context | all | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-source_context-all-1 | 4622ce35e4fff9fb02e351c85c3bb14186d3220595f5de6ab841de86c50a5caf | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'source_context'. Please ensure it is a valid JSON Schema. |
| openai/gpt-6.1-sol | financials | one-of-to-any-of | not applicable | not sent | - | 0 | none | - | - |
| openai/gpt-6.1-sol | financials | drop-format | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-financials-drop-format-1 | 46d12e439073b0a22235cc8557594f536bab74ab93c98ce7c502b44f6c876dfe | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'financials'. Please ensure it is a valid JSON Schema. |
| openai/gpt-6.1-sol | financials | drop-pattern | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-financials-drop-pattern-1 | 4e85074e79dcbd894b902dd35a7b063797fc188c0bfa87d54045fbde075a25fa | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'financials'. Please ensure it is a valid JSON Schema. |
| openai/gpt-6.1-sol | financials | drop-items-bounds | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-financials-drop-items-bounds-1 | f260bd7277da1819b0e062e825e9c053eb868d239ea0afe6cb7ddf05007d7fa2 | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'financials'. Please ensure it is a valid JSON Schema. |
| openai/gpt-6.1-sol | financials | open-object | not applicable | not sent | - | 0 | none | - | - |
| openai/gpt-6.1-sol | financials | any-of-null-to-type-union | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-financials-any-of-null-to-type-union-1 | 0eaea9c72d1f83866249642ab501feec2ec0ed3e77989c0e39c8055727710f46 | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'financials'. Please ensure it is a valid JSON Schema. |
| openai/gpt-6.1-sol | financials | split-mixed-types | not applicable | not sent | - | 0 | none | - | - |
| openai/gpt-6.1-sol | financials | all | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-financials-all-1 | 7be93aac30c64144792b1e9842163e8cf167e2c03fc048533412c6fe20594f56 | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'financials'. Please ensure it is a valid JSON Schema. |
| openai/gpt-6.1-sol | narrative | one-of-to-any-of | accepted | truncated | 200 | 0.001964 | openai__gpt-6.1-sol-narrative-one-of-to-any-of-1 | ff12e31f794e569798c72576f0165ae0b72ada69d534e678fb373af9a6de80b6 | - |
| openai/gpt-6.1-sol | readiness | one-of-to-any-of | not applicable | not sent | - | 0 | none | - | - |
| openai/gpt-6.1-sol | readiness | drop-format | not applicable | not sent | - | 0 | none | - | - |
| openai/gpt-6.1-sol | readiness | drop-pattern | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-readiness-drop-pattern-1 | 156564ed7d1b345b603d05a4e2eb4b4e5214a4cc86de4de4a057024dc81e5a2f | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'readiness'. Please ensure it is a valid JSON Schema. |
| openai/gpt-6.1-sol | readiness | drop-items-bounds | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-readiness-drop-items-bounds-1 | 07c2ffa79b2294ab8295da008d5e16e20208e1e027d2f0ed2387435268b3b9e6 | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'readiness'. Please ensure it is a valid JSON Schema. |
| openai/gpt-6.1-sol | readiness | open-object | not applicable | not sent | - | 0 | none | - | - |
| openai/gpt-6.1-sol | readiness | any-of-null-to-type-union | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-readiness-any-of-null-to-type-union-1 | 65bbf57245ded07e046ffb9d9d7af53f612562e063566212fe84f8da716ba77a | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'readiness'. Please ensure it is a valid JSON Schema. |
| openai/gpt-6.1-sol | readiness | split-mixed-types | not applicable | not sent | - | 0 | none | - | - |
| openai/gpt-6.1-sol | readiness | all | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-readiness-all-1 | 12c38e1cc14b30f075c296e6553690d6516462a853075b1033356f121e2dfdc2 | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'readiness'. Please ensure it is a valid JSON Schema. |
| google/gemini-4-argon | source_context | one-of-to-any-of | not applicable | not sent | - | 0 | none | - | - |
| google/gemini-4-argon | source_context | drop-format | http_error | http_error | 400 | 0 | google__gemini-4-argon-source_context-drop-format-1 | 146954989c7c6356e405205e1f61a9285d6b3b79471dfff5ec30e8183c44b49d | HTTP 400: Provider returned error; Google 400: Request contains an invalid argument. |
| google/gemini-4-argon | source_context | drop-pattern | http_error | http_error | 400 | 0 | google__gemini-4-argon-source_context-drop-pattern-1 | d428f3317853ff188aa9758656e8ebb0ce56a3f8c8f2c52e7cf47f8283d6a011 | HTTP 400: Provider returned error; Google 400: Request contains an invalid argument. |
| google/gemini-4-argon | source_context | drop-items-bounds | accepted | truncated | 200 | 0.006822 | google__gemini-4-argon-source_context-drop-items-bounds-1 | f3b38e7e30e26b723fe63b29b3b9c77af8d22076b7968f75da184f45cb708995 | - |
| google/gemini-4-argon | financials | one-of-to-any-of | not applicable | not sent | - | 0 | none | - | - |
| google/gemini-4-argon | financials | drop-format | http_error | http_error | 400 | 0 | google__gemini-4-argon-financials-drop-format-1 | 46d12e439073b0a22235cc8557594f536bab74ab93c98ce7c502b44f6c876dfe | HTTP 400: Provider returned error; Google 400: Request contains an invalid argument. |
| google/gemini-4-argon | financials | drop-pattern | http_error | http_error | 400 | 0 | google__gemini-4-argon-financials-drop-pattern-1 | 4e85074e79dcbd894b902dd35a7b063797fc188c0bfa87d54045fbde075a25fa | HTTP 400: Provider returned error; Google 400: Request contains an invalid argument. |
| google/gemini-4-argon | financials | drop-items-bounds | http_error | http_error | 400 | 0 | google__gemini-4-argon-financials-drop-items-bounds-1 | f260bd7277da1819b0e062e825e9c053eb868d239ea0afe6cb7ddf05007d7fa2 | HTTP 400: Provider returned error; Google 400: Request contains an invalid argument. |
| google/gemini-4-argon | financials | open-object | not applicable | not sent | - | 0 | none | - | - |
| google/gemini-4-argon | financials | any-of-null-to-type-union | http_error | http_error | 400 | 0 | google__gemini-4-argon-financials-any-of-null-to-type-union-1 | 0eaea9c72d1f83866249642ab501feec2ec0ed3e77989c0e39c8055727710f46 | HTTP 400: Provider returned error; Google 400: Request contains an invalid argument. |
| google/gemini-4-argon | financials | split-mixed-types | not applicable | not sent | - | 0 | none | - | - |
| google/gemini-4-argon | financials | all | http_error | http_error | 400 | 0 | google__gemini-4-argon-financials-all-1 | 7be93aac30c64144792b1e9842163e8cf167e2c03fc048533412c6fe20594f56 | HTTP 400: Provider returned error; Google 400: Request contains an invalid argument. |
| google/gemini-4-argon | narrative | one-of-to-any-of | http_error | http_error | 400 | 0 | google__gemini-4-argon-narrative-one-of-to-any-of-1 | ff12e31f794e569798c72576f0165ae0b72ada69d534e678fb373af9a6de80b6 | HTTP 400: Provider returned error; Google 400: Request contains an invalid argument. |
| google/gemini-4-argon | narrative | drop-format | not applicable | not sent | - | 0 | none | - | - |
| google/gemini-4-argon | narrative | drop-pattern | http_error | http_error | 400 | 0 | google__gemini-4-argon-narrative-drop-pattern-1 | 88d8cfc472254ac7f401d4a1e5e653eb407b6a81e43db34d5f0d77459da516a2 | HTTP 400: Provider returned error; Google 400: Request contains an invalid argument. |
| google/gemini-4-argon | narrative | drop-items-bounds | accepted | truncated | 200 | 0.005566 | google__gemini-4-argon-narrative-drop-items-bounds-1 | 180d172932b3a42ea14c9d58024146b166246230d26e4031fd6253932ce84fb6 | - |

## First accepted variant

- openai/gpt-6.1-sol source_context: none accepted
- openai/gpt-6.1-sol financials: none accepted
- openai/gpt-6.1-sol narrative: first accepted variant: one-of-to-any-of
- openai/gpt-6.1-sol readiness: none accepted
- google/gemini-4-argon source_context: first accepted variant: drop-items-bounds
- google/gemini-4-argon financials: none accepted
- google/gemini-4-argon narrative: first accepted variant: drop-items-bounds
