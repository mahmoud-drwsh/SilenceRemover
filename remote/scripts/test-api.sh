#!/bin/bash
# Test all API endpoints
# Usage: ./test-api.sh [token]

cd "$(dirname "$0")/.."

TOKEN="${1:-local-test}"
BASE_URL="http://localhost:8080/$TOKEN"
PROJECT="test-project"
API="$BASE_URL/$PROJECT"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0

test_step() {
    echo -e "${YELLOW}▶ $1${NC}"
}

test_pass() {
    echo -e "${GREEN}  ✓ $1${NC}"
    ((PASS++))
}

test_fail() {
    echo -e "${RED}  ✗ $1${NC}"
    echo "    $2"
    ((FAIL++))
}

echo "Testing API at: $API"
echo ""

# Generate test audio if not exists
if [ ! -f "./test-audio/001_test_s.mp3" ]; then
    ./scripts/generate-test-audio.sh 2>/dev/null
fi

# 1. Upload file
test_step "1. Upload file"
RESPONSE=$(curl -s -X POST "$API/upload" \
    -F "id=001" \
    -F "title=First Test Audio" \
    -F "file=@./test-audio/001_test_s.mp3")
if echo "$RESPONSE" | grep -q '"ok": true'; then
    test_pass "Upload 001 succeeded"
else
    test_fail "Upload 001 failed" "$RESPONSE"
fi

# 2. Upload second file
RESPONSE=$(curl -s -X POST "$API/upload" \
    -F "id=002" \
    -F "title=Second Test Audio" \
    -F "file=@./test-audio/002_test_s.mp3")
if echo "$RESPONSE" | grep -q '"ok": true'; then
    test_pass "Upload 002 succeeded"
else
    test_fail "Upload 002 failed" "$RESPONSE"
fi

# 3. List files
test_step "2. List files"
RESPONSE=$(curl -s "$API/api/files")
COUNT=$(echo "$RESPONSE" | grep -o '"id"' | wc -l)
if [ "$COUNT" -eq 2 ]; then
    test_pass "List returns 2 files"
else
    test_fail "List returned $COUNT files, expected 2" "$RESPONSE"
fi

# 4. Update title
test_step "3. Update title"
RESPONSE=$(curl -s -X POST "$API/api/update/001" \
    -F "title=Updated Title")
if echo "$RESPONSE" | grep -q '"ok": true'; then
    test_pass "Title update succeeded"
else
    test_fail "Title update failed" "$RESPONSE"
fi

# Verify title changed
RESPONSE=$(curl -s "$API/api/files")
if echo "$RESPONSE" | grep -q '"Updated Title"'; then
    test_pass "Title change verified"
else
    test_fail "Title change not found in list" "$RESPONSE"
fi

# 5. Toggle ready
test_step "4. Toggle ready status"
RESPONSE=$(curl -s -X POST "$API/api/toggle-ready/001" \
    -H "Content-Type: application/json" \
    -d '{"ready": true}')
if echo "$RESPONSE" | grep -q '"ok": true'; then
    test_pass "Toggle ready succeeded"
else
    test_fail "Toggle ready failed" "$RESPONSE"
fi

# Verify ready status
RESPONSE=$(curl -s "$API/api/files")
if echo "$RESPONSE" | grep -q '"ready": 1'; then
    test_pass "Ready status verified"
else
    test_fail "Ready status not found" "$RESPONSE"
fi

# 6. Move to trash
test_step "5. Move to trash"
RESPONSE=$(curl -s -X POST "$API/api/trash/002")
if echo "$RESPONSE" | grep -q '"ok": true'; then
    test_pass "Trash succeeded"
else
    test_fail "Trash failed" "$RESPONSE"
fi

# Verify trashed file not in active list
RESPONSE=$(curl -s "$API/api/files")
if echo "$RESPONSE" | grep -q '"trashed": 1'; then
    test_pass "Trashed file found in list"
else
    test_fail "Trashed file status not found" "$RESPONSE"
fi

# 7. Restore from trash
test_step "6. Restore from trash"
RESPONSE=$(curl -s -X POST "$API/api/restore/002")
if echo "$RESPONSE" | grep -q '"ok": true'; then
    test_pass "Restore succeeded"
else
    test_fail "Restore failed" "$RESPONSE"
fi

# 8. Stream file
test_step "7. Stream file"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$API/stream/001")
if [ "$HTTP_CODE" -eq 200 ]; then
    test_pass "Stream returns 200"
else
    test_fail "Stream returned $HTTP_CODE" ""
fi

# 9. Delete permanently
test_step "8. Delete permanently"
RESPONSE=$(curl -s -X POST "$API/api/delete/002")
if echo "$RESPONSE" | grep -q '"ok": true'; then
    test_pass "Delete succeeded"
else
    test_fail "Delete failed" "$RESPONSE"
fi

# Verify only 1 file remains
RESPONSE=$(curl -s "$API/api/files")
COUNT=$(echo "$RESPONSE" | grep -o '"id"' | wc -l)
if [ "$COUNT" -eq 1 ]; then
    test_pass "Only 1 file remains after delete"
else
    test_fail "Found $COUNT files, expected 1" "$RESPONSE"
fi

# Summary
echo ""
echo "========================"
echo -e "${GREEN}Passed: $PASS${NC}"
echo -e "${RED}Failed: $FAIL${NC}"
echo "========================"

if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}All tests passed! Ready to deploy.${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed. Check before deploying.${NC}"
    exit 1
fi
