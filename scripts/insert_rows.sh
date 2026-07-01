#!/bin/bash
DS_ID="4322147e-e916-43eb-a959-0b4925a8dfc8"

insert_row() {
  NAME=$1
  SYMBOL=$2
  ANZAHL=$3
  KAUFKURS=$4
  PREIS=$5
  GESAMT=$6
  
  cat << JSON > row.json
  {
    "parent": { "data_source_id": "$DS_ID" },
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
  if [ $? -eq 0 ]; then
    echo "Inserted $NAME"
  else
    echo "Failed to insert $NAME"
  fi
}

insert_row "Oracle Corp" "ORCL" 25 159.0 131.92 3298.00
insert_row "Salesforce Inc" "CRM" 20 162.0 215.50 4310.00
insert_row "iShares Nasdaq-100" "SXRV" 1 1475.0 1550.00 1550.00
insert_row "iShares Aerospace" "ITA" 18 235.0 242.00 4356.00
