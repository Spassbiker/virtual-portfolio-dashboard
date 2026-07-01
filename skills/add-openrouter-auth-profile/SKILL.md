---
name: "add-openrouter-auth-profile"
description: "Create auth profile for OpenRouter provider."
---

# Proposal: Create OpenRouter Auth Profile

This proposal registers the `openrouter:default` authentication profile, which is required to link the OpenRouter provider to your API key credentials.

## Configuration

```json
{
  "openrouter:default": {
    "provider": "openrouter",
    "mode": "api_key"
  }
}
```

## Instructions
1. Apply this proposal.
2. Once applied, your OpenClaw Gateway will recognize the `openrouter:default` auth profile.
3. You will need to provide your actual API key to the system (typically via your Gateway's secret management interface or by following your specific system's instructions for linking credentials to named auth profiles).
```
