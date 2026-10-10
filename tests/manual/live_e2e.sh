#!/bin/bash
# Manual live acceptance test: real fal.ai TTS + Kling avatar + FFmpeg render. Costs real provider credits.
set -e
API=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d= -f2)/api/v1
TOKEN=$(curl -s -X POST $API/auth/login -H 'Content-Type: application/json' -d '{"email":"admin@anchorai.news","password":"AnchorAdmin@2026"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
H="Authorization: Bearer $TOKEN"
WS=$(curl -s $API/workspaces/current -H "$H" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -s -X POST $API/admin/credits/adjust -H "$H" -H 'Content-Type: application/json' -d "{\"workspace_id\":\"$WS\",\"amount\":200,\"reason\":\"Live acceptance test credits\"}"; echo
curl -sL -o /app/tests/manual/portrait.jpg "https://images.unsplash.com/photo-1781888681811-332968760c2a?crop=entropy&cs=srgb&fm=jpg&q=85&w=1024"
ANCHOR=$(curl -s -X POST $API/anchors -H "$H" -F file=@/app/tests/manual/portrait.jpg -F display_name="Test Anchor" -F authorized_by="Test Presenter" -F consent_basis=licensed_presenter -F consent_confirmed=true -F consent_version=2026-06-v1 | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('id') or d)")
echo anchor=$ANCHOR
PROJ=$(curl -s -X POST $API/projects -H "$H" -H 'Content-Type: application/json' -d "{\"name\":\"Live test bulletin\",\"anchor_id\":\"$ANCHOR\",\"script\":\"નમસ્તે, આપ જોઈ રહ્યા છો તાજા સમાચાર. આજે અમદાવાદમાં ભારે વરસાદ પડ્યો છે અને શાળાઓમાં રજા જાહેર કરવામાં આવી છે.\",\"headline\":\"અમદાવાદમાં ભારે વરસાદ\",\"location\":\"અમદાવાદ\",\"voice\":\"Sarah\",\"branding\":{\"channel_name\":\"ગુજરાત લાઇવ\",\"ticker_text\":\"રાજ્યમાં ચોમાસું સક્રિય\",\"show_date\":true,\"intro_enabled\":true,\"outro_enabled\":false}}" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo project=$PROJ
curl -s -X POST $API/projects/$PROJ/generate -H "$H" -H "Idempotency-Key: live-test-$(date +%s)-abcdef" -H 'Content-Type: application/json' -d '{"consent_confirmed":true}' | python3 -c "import sys,json;d=json.load(sys.stdin);print('job',d.get('id'),d.get('status'),d.get('reserved_credits'),d)" 
