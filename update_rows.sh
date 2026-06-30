#!/bin/bash
DS_ID="4322147e-e916-43eb-a959-0b4925a8dfc8"

# Hole alle Pages in dieser Data Source
RES=$(ntn datasources query "$DS_ID" --json)

# Oracle
ORCL_ID=$(echo "$RES" | jq -r '.results[] | select(.properties.Symbol.rich_text[0].text.content == "ORCL") | .id')
cat << JSON > patch.json
{
  "properties": {
    "Kaufsumme": { "number": 3975.00 }
  }
}
JSON
ntn api v1/pages/$ORCL_ID -X PATCH --data @patch.json > /dev/null

# Salesforce
CRM_ID=$(echo "$RES" | jq -r '.results[] | select(.properties.Symbol.rich_text[0].text.content == "CRM") | .id')
cat << JSON > patch.json
{
  "properties": {
    "Kaufsumme": { "number": 3240.00 }
  }
}
JSON
ntn api v1/pages/$CRM_ID -X PATCH --data @patch.json > /dev/null

# iShares Nasdaq
SXRV_ID=$(echo "$RES" | jq -r '.results[] | select(.properties.Symbol.rich_text[0].text.content == "SXRV") | .id')
cat << JSON > patch.json
{
  "properties": {
    "Kaufsumme": { "number": 1475.00 }
  }
}
JSON
ntn api v1/pages/$SXRV_ID -X PATCH --data @patch.json > /dev/null

# iShares Aerospace
ITA_ID=$(echo "$RES" | jq -r '.results[] | select(.properties.Symbol.rich_text[0].text.content == "ITA") | .id')
cat << JSON > patch.json
{
  "properties": {
    "Kaufsumme": { "number": 4230.00 }
  }
}
JSON
ntn api v1/pages/$ITA_ID -X PATCH --data @patch.json > /dev/null

echo "Update abgeschlossen"
