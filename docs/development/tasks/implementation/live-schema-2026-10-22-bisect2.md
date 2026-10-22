# Live batch schema-2026-10-22-bisect2 (schema-check)

- Command: schema-check (one strict response_format call per model and step; max_tokens 16, no reasoning parameter, nothing submitted)
- Steps: source_context, financials, readiness
- Cap: 0.10 USD; reserved 0, spent 0.0174925, remaining 0.0825075
- Catalog: `openrouter-models-2026-10-21.json`, the coordinator's saved models file (not in the repository; sha256 b17fc211fe65e4347e6808adbb2d35b4d2106aca90e690a81fcc5e66c6b89c9f), looked up 2026-10-22T07:09:04Z
- Accepted: 0; http_error: 3; other: 0; ineligible: 0; refused: 0
- Bisect: yes (variants are reported only; no real run sends them)
- Stopped: no

## Results

| Model | Step | Outcome | Class | HTTP | USD | Attempt | Sent schema sha256 | Relaxations | Keywords | Blocks later runs | Provider detail |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| openai/gpt-6.1-sol | source_context | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-source_context-1 | 75eb31361020ae3529cf52488b31297bb2fbc4f0db73db0fb1890c89ba8335eb | nullable-enum, const-to-enum, drop-length | $defs, $ref, additionalProperties, anyOf, enum, format, items, maxItems, minItems, pattern, properties, required, type; depth 8 (4 objects), 52 properties | yes: schema rejection | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'source_context'. Please ensure it is a valid JSON Schema. |
| openai/gpt-6.1-sol | financials | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-financials-1 | ccf6aab259df5c487bb2aaa3223c31ecee546cc9405908822449387303bf8f33 | nullable-enum, const-to-enum, drop-length | $defs, $ref, additionalProperties, anyOf, enum, exclusiveMaximum, exclusiveMinimum, format, items, maxItems, maximum, minItems, minimum, pattern, properties, required, type; depth 12 (7 objects), 232 properties | yes: schema rejection | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'financials'. Please ensure it is a valid JSON Schema. |
| openai/gpt-6.1-sol | readiness | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-readiness-1 | 6efd5a9f971a84a91276f483ed097310f370c390753abda78c619f269cee328b | const-to-enum, drop-length | $defs, $ref, additionalProperties, anyOf, enum, items, minItems, pattern, properties, required, type; depth 7 (3 objects), 15 properties | yes: schema rejection | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'readiness'. Please ensure it is a valid JSON Schema. |

`Blocks later runs` `no: the 400 does not name the schema`: the provider gave no schema reason (Google's is only "Request contains an invalid argument"), so the cell stays eligible.

## Bisect

| Model | Step | Variant | Outcome | Class | HTTP | USD | Attempt | Variant schema sha256 | Provider detail | Touches |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| openai/gpt-6.1-sol | source_context | one-of-to-any-of | not applicable | not sent | - | 0 | none | - | - | - |
| openai/gpt-6.1-sol | source_context | drop-format | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-source_context-drop-format-1 | 146954989c7c6356e405205e1f61a9285d6b3b79471dfff5ec30e8183c44b49d | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'source_context'. Please ensure it is a valid JSON Schema. | - |
| openai/gpt-6.1-sol | source_context | drop-pattern | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-source_context-drop-pattern-1 | d428f3317853ff188aa9758656e8ebb0ce56a3f8c8f2c52e7cf47f8283d6a011 | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'source_context'. Please ensure it is a valid JSON Schema. | - |
| openai/gpt-6.1-sol | source_context | drop-items-bounds | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-source_context-drop-items-bounds-1 | f3b38e7e30e26b723fe63b29b3b9c77af8d22076b7968f75da184f45cb708995 | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'source_context'. Please ensure it is a valid JSON Schema. | - |
| openai/gpt-6.1-sol | source_context | open-object | not applicable | not sent | - | 0 | none | - | - | - |
| openai/gpt-6.1-sol | source_context | any-of-null-to-type-union | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-source_context-any-of-null-to-type-union-1 | f317ec127ba13daba36671541f16796883845d8eb9f9fc6b1632ff33c289bb9f | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'source_context'. Please ensure it is a valid JSON Schema. | - |
| openai/gpt-6.1-sol | source_context | split-mixed-types | not applicable | not sent | - | 0 | none | - | - | - |
| openai/gpt-6.1-sol | source_context | nullable-array-to-anyof | accepted | truncated | 200 | 0.0033835 | openai__gpt-6.1-sol-source_context-nullable-array-to-anyof-1 | f96cc532eb796cfa61f6c1edfc972e8c1c103a8e3fe9a4c011953cb1fabc1434 | - | - |
| openai/gpt-6.1-sol | financials | one-of-to-any-of | not applicable | not sent | - | 0 | none | - | - | - |
| openai/gpt-6.1-sol | financials | drop-format | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-financials-drop-format-1 | 46d12e439073b0a22235cc8557594f536bab74ab93c98ce7c502b44f6c876dfe | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'financials'. Please ensure it is a valid JSON Schema. | - |
| openai/gpt-6.1-sol | financials | drop-pattern | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-financials-drop-pattern-1 | 4e85074e79dcbd894b902dd35a7b063797fc188c0bfa87d54045fbde075a25fa | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'financials'. Please ensure it is a valid JSON Schema. | - |
| openai/gpt-6.1-sol | financials | drop-items-bounds | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-financials-drop-items-bounds-1 | f260bd7277da1819b0e062e825e9c053eb868d239ea0afe6cb7ddf05007d7fa2 | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'financials'. Please ensure it is a valid JSON Schema. | - |
| openai/gpt-6.1-sol | financials | open-object | not applicable | not sent | - | 0 | none | - | - | - |
| openai/gpt-6.1-sol | financials | any-of-null-to-type-union | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-financials-any-of-null-to-type-union-1 | 0eaea9c72d1f83866249642ab501feec2ec0ed3e77989c0e39c8055727710f46 | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'financials'. Please ensure it is a valid JSON Schema. | - |
| openai/gpt-6.1-sol | financials | split-mixed-types | not applicable | not sent | - | 0 | none | - | - | - |
| openai/gpt-6.1-sol | financials | nullable-array-to-anyof | accepted | truncated | 200 | 0.013111 | openai__gpt-6.1-sol-financials-nullable-array-to-anyof-1 | 775b87aab382eee61981353bf0ff92969584dd323d7cd9a1bbf2891da71f5ed2 | - | - |
| openai/gpt-6.1-sol | readiness | one-of-to-any-of | not applicable | not sent | - | 0 | none | - | - | - |
| openai/gpt-6.1-sol | readiness | drop-format | not applicable | not sent | - | 0 | none | - | - | - |
| openai/gpt-6.1-sol | readiness | drop-pattern | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-readiness-drop-pattern-1 | 156564ed7d1b345b603d05a4e2eb4b4e5214a4cc86de4de4a057024dc81e5a2f | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'readiness'. Please ensure it is a valid JSON Schema. | - |
| openai/gpt-6.1-sol | readiness | drop-items-bounds | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-readiness-drop-items-bounds-1 | 07c2ffa79b2294ab8295da008d5e16e20208e1e027d2f0ed2387435268b3b9e6 | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'readiness'. Please ensure it is a valid JSON Schema. | - |
| openai/gpt-6.1-sol | readiness | open-object | not applicable | not sent | - | 0 | none | - | - | - |
| openai/gpt-6.1-sol | readiness | any-of-null-to-type-union | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-readiness-any-of-null-to-type-union-1 | 65bbf57245ded07e046ffb9d9d7af53f612562e063566212fe84f8da716ba77a | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'readiness'. Please ensure it is a valid JSON Schema. | - |
| openai/gpt-6.1-sol | readiness | split-mixed-types | not applicable | not sent | - | 0 | none | - | - | - |
| openai/gpt-6.1-sol | readiness | nullable-array-to-anyof | accepted | truncated | 200 | 0.000998 | openai__gpt-6.1-sol-readiness-nullable-array-to-anyof-1 | b385bf970aa9c6e3b5f557f98645e23f6c14f4f44ee379c512f23ff0da444b57 | - | - |

## First accepted variant

- openai/gpt-6.1-sol source_context: first accepted variant: nullable-array-to-anyof
- openai/gpt-6.1-sol financials: first accepted variant: nullable-array-to-anyof
- openai/gpt-6.1-sol readiness: first accepted variant: nullable-array-to-anyof
