---
name: "add-openrouter-owl-alpha"
description: "Add OpenRouter provider and Owl Alpha model configuration to OpenClaw."
---

# Proposal: Add OpenRouter Provider

This proposal adds OpenRouter as a provider to the OpenClaw model catalog, specifically enabling `openrouter/owl-alpha`.

## Configuration

```json
{
  "openrouter": {
    "apiKey": "REQUIRED_SET_VIA_SECRET_OR_ENV",
    "api": "openai",
    "baseUrl": "https://openrouter.ai/api/v1",
    "models": [
      {
        "id": "openrouter/owl-alpha",
        "name": "Owl Alpha",
        "contextWindow": 1000000,
        "maxTokens": 262000,
        "compat": {
          "supportsTools": true,
          "supportsUsageInStreaming": true
        },
        "api": "openai"
      }
    ]
  }
}
```

## Instructions
1. Apply this proposal.
2. Ensure your OpenRouter API key is configured in the environment or secret manager as required by your OpenClaw setup.
```
