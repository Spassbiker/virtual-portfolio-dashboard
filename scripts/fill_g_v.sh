#!/bin/bash
DS_ID="4322147e-e916-43eb-a959-0b4925a8dfc8"
RES=$(ntn datasources query "$DS_ID" --json)

# Oracle
ORCL_ID=$(echo "$RES" | jq -r '.results[] | select(.properties.Symbol.rich_text[0].text.content == "ORCL") | .id')
ntn api v1/pages/$ORCL_ID -X PATCH --data '{"properties":{"Gewinn_Verlust":{"number":-677.00}}}'

# Salesforce
CRM_ID=$(echo "$RES" | jq -r '.results[] | select(.properties.Symbol.rich_text[0].text.content == "CRM") | .id')
ntn api v1/pages/$CRM_ID -X PATCH --data '{"properties":{"Gewinn_Verlust":{"number":1070.00}}}'

# SXRV
SXRV_ID=$(echo "$RES" | jq -r '.results[] | select(.properties.Symbol.rich_text[0].text.content == "SXRV") | .id')
ntn api v1/pages/$SXRV_ID -X PATCH --data '{"properties":{"Gewinn_Verlust":{"number":75.00}}}'

# ITA
ITA_ID=$(echo "$RES" | jq -r '.results[] | select(.properties.Symbol.rich_text[0].text.content == "ITA") | .id')
ntn api v1/pages/$ITA_ID -X PATCH --data '{"properties":{"Gewinn_Verlust":{"number":126.00}}}'
