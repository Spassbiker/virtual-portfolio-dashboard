#!/bin/bash

# 1. Create the Database definition
cat << 'JSON' > create_db.json
{
  "parent": { "type": "page_id", "page_id": "38d42c0b-de77-8047-aa90-c6e2d1ce2283" },
  "title": [ { "type": "text", "text": { "content": "Mein Aktien-Depot" } } ],
  "properties": {
    "Name": { "title": {} },
    "Symbol": { "rich_text": {} },
    "Anzahl": { "number": { "format": "number" } },
    "Kaufkurs": { "number": { "format": "euro" } },
    "Börsenpreis": { "number": { "format": "euro" } },
    "Gesamtwert": { "number": { "format": "euro" } }
  }
}
JSON

# 2. Call Notion API to create the database
RES=$(ntn api v1/databases -X POST --data @create_db.json)

# 3. Extract Database ID using jq
DB_ID=$(echo "$RES" | jq -r .id)

if [ "$DB_ID" == "null" ] || [ -z "$DB_ID" ]; then
  echo "Failed to create database:"
  echo "$RES"
  exit 1
fi
echo "Database created successfully. ID: $DB_ID"

# 4. Insert rows
insert_row() {
  NAME=$1
  SYMBOL=$2
  ANZAHL=$3
  KAUFKURS=$4
  PREIS=$5
  GESAMT=$6
  
  cat << JSON > row.json
  {
    "parent": { "database_id": "$DB_ID" },
    "properties": {
      "Name": { "title": [ { "text": { "content": "$NAME" } } ] },
      "Symbol": { "rich_text": [ { "text": { "content": "$SYMBOL" } } ] },
      "Anzahl": { "number": $ANZAHL },
      "Kaufkurs": { "number": $KAUFKURS },
      "Börsenpreis": { "number": $PREIS },
      "Gesamtwert": { "number": $GESAMT }
    }
  }
JSON
  ntn api v1/pages -X POST --data @row.json > /dev/null
  echo "Inserted $NAME"
}

insert_row "Oracle Corp" "ORCL" 25 159.0 131.92 3298.00
insert_row "Salesforce Inc" "CRM" 20 162.0 215.50 4310.00
insert_row "iShares Nasdaq-100" "SXRV" 1 1475.0 1550.00 1550.00
insert_row "iShares Aerospace" "ITA" 18 235.0 242.00 4356.00

echo "Done! URL: https://app.notion.com/p/${DB_ID//-/}"
