# Live batch schema-2026-10-22 (schema-check)

- Command: schema-check (one strict response_format call per model and step; max_tokens 16, no reasoning parameter, nothing submitted)
- Steps: source_readiness, source_context, financials, narrative, readiness
- Cap: 0.10 USD; reserved 0, spent 0.077742, remaining 0.022258
- Catalog: `openrouter-models-2026-10-21.json`, the coordinator's saved models file (not in the repository; sha256 b17fc211fe65e4347e6808adbb2d35b4d2106aca90e690a81fcc5e66c6b89c9f), looked up 2026-10-22T05:54:13Z
- Accepted: 8; http_error: 7; other: 0; ineligible: 0; refused: 0
- Stopped: no

## Results

| Model | Step | Outcome | Class | HTTP | USD | Attempt | Sent schema sha256 | Relaxations | Provider detail |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| openai/gpt-6.1-sol | source_readiness | accepted | truncated | 200 | 0.001852 | openai__gpt-6.1-sol-source_readiness-1 | 762998c99711498cf1f13a6342a233c0c72dc44b5e37cad6c7cad7f42c18ae06 | none | - |
| openai/gpt-6.1-sol | source_context | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-source_context-1 | 75eb31361020ae3529cf52488b31297bb2fbc4f0db73db0fb1890c89ba8335eb | nullable-enum, const-to-enum, drop-length | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'source_context'. Please ensure it is a valid JSON Schema. |
| openai/gpt-6.1-sol | financials | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-financials-1 | ccf6aab259df5c487bb2aaa3223c31ecee546cc9405908822449387303bf8f33 | nullable-enum, const-to-enum, drop-length | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'financials'. Please ensure it is a valid JSON Schema. |
| openai/gpt-6.1-sol | narrative | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-narrative-1 | 58e27e482b6078d7bc09217565c09151913b2aa48bfc297bf6b0b96260881b42 | const-to-enum, drop-length | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'narrative': In context=('properties', 'rationale', 'items'), 'oneOf' is not permitted. |
| openai/gpt-6.1-sol | readiness | http_error | http_error | 400 | 0 | openai__gpt-6.1-sol-readiness-1 | 6efd5a9f971a84a91276f483ed097310f370c390753abda78c619f269cee328b | const-to-enum, drop-length | HTTP 400: Provider returned error; OpenAI invalid_json_schema: Invalid schema for response_format 'readiness'. Please ensure it is a valid JSON Schema. |
| x-ai/grok-4.7 | source_readiness | accepted | truncated | 200 | 0.006352 | x-ai__grok-4.7-source_readiness-1 | 762998c99711498cf1f13a6342a233c0c72dc44b5e37cad6c7cad7f42c18ae06 | none | - |
| x-ai/grok-4.7 | source_context | accepted | truncated | 200 | 0.011638 | x-ai__grok-4.7-source_context-1 | 75eb31361020ae3529cf52488b31297bb2fbc4f0db73db0fb1890c89ba8335eb | nullable-enum, const-to-enum, drop-length | - |
| x-ai/grok-4.7 | financials | accepted | truncated | 200 | 0.036414 | x-ai__grok-4.7-financials-1 | ccf6aab259df5c487bb2aaa3223c31ecee546cc9405908822449387303bf8f33 | nullable-enum, const-to-enum, drop-length | - |
| x-ai/grok-4.7 | narrative | accepted | truncated | 200 | 0.00813 | x-ai__grok-4.7-narrative-1 | 58e27e482b6078d7bc09217565c09151913b2aa48bfc297bf6b0b96260881b42 | const-to-enum, drop-length | - |
| x-ai/grok-4.7 | readiness | accepted | truncated | 200 | 0.007632 | x-ai__grok-4.7-readiness-1 | 6efd5a9f971a84a91276f483ed097310f370c390753abda78c619f269cee328b | const-to-enum, drop-length | - |
| google/gemini-4-argon | source_readiness | accepted | truncated | 200 | 0.003682 | google__gemini-4-argon-source_readiness-1 | 762998c99711498cf1f13a6342a233c0c72dc44b5e37cad6c7cad7f42c18ae06 | none | - |
| google/gemini-4-argon | source_context | http_error | http_error | 400 | 0 | google__gemini-4-argon-source_context-1 | 75eb31361020ae3529cf52488b31297bb2fbc4f0db73db0fb1890c89ba8335eb | nullable-enum, const-to-enum, drop-length | HTTP 400: Provider returned error; Google 400: Request contains an invalid argument. |
| google/gemini-4-argon | financials | http_error | http_error | 400 | 0 | google__gemini-4-argon-financials-1 | ccf6aab259df5c487bb2aaa3223c31ecee546cc9405908822449387303bf8f33 | nullable-enum, const-to-enum, drop-length | HTTP 400: Provider returned error; Google 400: Request contains an invalid argument. |
| google/gemini-4-argon | narrative | http_error | http_error | 400 | 0 | google__gemini-4-argon-narrative-1 | 58e27e482b6078d7bc09217565c09151913b2aa48bfc297bf6b0b96260881b42 | const-to-enum, drop-length | HTTP 400: Provider returned error; Google 400: Request contains an invalid argument. |
| google/gemini-4-argon | readiness | accepted | truncated | 200 | 0.002042 | google__gemini-4-argon-readiness-1 | 6efd5a9f971a84a91276f483ed097310f370c390753abda78c619f269cee328b | const-to-enum, drop-length | - |
