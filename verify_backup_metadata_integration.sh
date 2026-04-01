#!/bin/bash
# Backup Metadata Integration Verification Script
# Checks that all components are correctly modified

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║   Backup Metadata Integration - Verification Script           ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

ERRORS=0

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

check_pass() {
    echo -e "${GREEN}✓${NC} $1"
}

check_fail() {
    echo -e "${RED}✗${NC} $1"
    ERRORS=$((ERRORS + 1))
}

check_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# ============================================================================
# SECTION 1: Python Files
# ============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1. Python Syntax Validation"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if python3 -m py_compile datastore-attacher/prescan/cli.py 2>/dev/null; then
    check_pass "prescan/cli.py syntax valid"
else
    check_fail "prescan/cli.py has syntax errors"
fi

if python3 -m py_compile datastore-attacher/shared/backup_detection/tvk_detector.py 2>/dev/null; then
    check_pass "tvk_detector.py syntax valid"
else
    check_fail "tvk_detector.py has syntax errors"
fi

# ============================================================================
# SECTION 2: Go Compilation
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2. Go Compilation"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if go build ./internal/... 2>/dev/null; then
    check_pass "internal/ package builds"
else
    check_fail "internal/ package has build errors"
fi

if go build ./pkg/helpers/... 2>/dev/null; then
    check_pass "pkg/helpers/ package builds"
else
    check_fail "pkg/helpers/ package has build errors"
fi

if go build ./controllers/... 2>/dev/null; then
    check_pass "controllers/ package builds"
else
    check_fail "controllers/ package has build errors"
fi

# ============================================================================
# SECTION 3: Constants Verification
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3. Go Constants Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if grep -q "BackupCreationTimestampAnnotation" internal/constants.go; then
    check_pass "BackupCreationTimestampAnnotation constant defined"
else
    check_fail "BackupCreationTimestampAnnotation constant missing"
fi

if grep -q "InstanceIDLabel" internal/constants.go; then
    check_pass "InstanceIDLabel constant defined"
else
    check_fail "InstanceIDLabel constant missing"
fi

if grep -q "BackupTargetLabel" internal/constants.go; then
    check_pass "BackupTargetLabel constant defined"
else
    check_fail "BackupTargetLabel constant missing"
fi

if grep -q "BackupPlanLabel" internal/constants.go; then
    check_pass "BackupPlanLabel constant defined"
else
    check_fail "BackupPlanLabel constant missing"
fi

if grep -q "BackupLabel" internal/constants.go; then
    check_pass "BackupLabel constant defined"
else
    check_fail "BackupLabel constant missing"
fi

# ============================================================================
# SECTION 4: Prescan Code Verification
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "4. Prescan Implementation Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if grep -q "backup_creation_timestamp" datastore-attacher/shared/backup_detection/tvk_detector.py; then
    check_pass "Detector extracts backup_creation_timestamp"
else
    check_fail "Detector does not extract backup_creation_timestamp"
fi

if grep -q "backupplan_name" datastore-attacher/shared/backup_detection/tvk_detector.py; then
    check_pass "Detector extracts backupplan_name"
else
    check_fail "Detector does not extract backupplan_name"
fi

if grep -q "'trilio.io/backup-creation-timestamp'" datastore-attacher/prescan/cli.py; then
    check_pass "Prescan adds backup-creation-timestamp annotation"
else
    check_fail "Prescan does not add backup-creation-timestamp annotation"
fi

# Labels should already exist (no new labels added)
if grep -q "'trilio.io/instance-id'" datastore-attacher/prescan/cli.py; then
    check_pass "Prescan sets instance-id label (existing)"
else
    check_fail "Prescan does not set instance-id label"
fi

if grep -q "'trilio.io/backup-target'" datastore-attacher/prescan/cli.py; then
    check_pass "Prescan sets backup-target label (existing)"
else
    check_fail "Prescan does not set backup-target label"
fi

# ============================================================================
# SECTION 5: Controller Code Verification
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "5. Controller Implementation Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if grep -q "backupMetadata := make(map\[string\]string)" pkg/helpers/job_helper.go; then
    check_pass "Controller creates backupMetadata map"
else
    check_fail "Controller does not create backupMetadata map"
fi

if grep -q "BackupCreationTimestampAnnotation" pkg/helpers/job_helper.go; then
    check_pass "Controller reads backup-creation-timestamp annotation"
else
    check_fail "Controller does not read backup-creation-timestamp annotation"
fi

if grep -q "InstanceIDLabel" pkg/helpers/job_helper.go; then
    check_pass "Controller reads instance-id label"
else
    check_fail "Controller does not read instance-id label"
fi

if grep -q "BackupLabel" pkg/helpers/job_helper.go; then
    check_pass "Controller reads backup label"
else
    check_fail "Controller does not read backup label"
fi

if grep -q "BackupTargetLabel" pkg/helpers/job_helper.go; then
    check_pass "Controller reads backup-target label"
else
    check_fail "Controller does not read backup-target label"
fi

if grep -q "BackupPlanLabel" pkg/helpers/job_helper.go; then
    check_pass "Controller reads backupplan label"
else
    check_fail "Controller does not read backupplan label"
fi

if grep -q "vm_collection_metadata" pkg/helpers/job_helper.go; then
    check_pass "Controller generates vm_collection_metadata"
else
    check_fail "Controller does not generate vm_collection_metadata"
fi

if grep -q "backupMetadata map\[string\]string" pkg/helpers/job_helper.go; then
    check_pass "GetScanConfigMapData accepts backupMetadata parameter"
else
    check_fail "GetScanConfigMapData signature not updated"
fi

if grep -q 'instance_id' pkg/helpers/job_helper.go; then
    check_pass "Controller includes instance_id in metadata"
else
    check_fail "Controller does not include instance_id"
fi

# ============================================================================
# SECTION 6: Integration Points
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "6. Integration Point Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if grep -q "metadata\.get('backup_creation_timestamp'" datastore-attacher/shared/backup_detection/tvk_detector.py; then
    check_pass "Detector safely handles missing creationTimestamp"
else
    check_warn "Detector may not handle missing creationTimestamp"
fi

if grep -q "if.*ok.*&&.*!=" pkg/helpers/job_helper.go; then
    check_pass "Controller checks for non-empty metadata fields"
else
    check_warn "Controller may not validate metadata fields"
fi

# Check cluster backup handling
if grep -q "clusterBackupPlan" datastore-attacher/shared/backup_detection/tvk_detector.py; then
    check_pass "Detector handles cluster backup plan name"
else
    check_fail "Detector does not handle cluster backup plan name"
fi

# ============================================================================
# SECTION 7: Documentation
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "7. Documentation Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

DOCS=(
    "BACKUP_METADATA_FLOW.md"
    "BACKUP_METADATA_QUICK_REF.md"
    "BACKUP_METADATA_VISUAL_GUIDE.md"
    "BACKUP_METADATA_TESTING_GUIDE.md"
    "BACKUP_METADATA_CHANGES_SUMMARY.md"
    "BACKUP_METADATA_IMPLEMENTATION_COMPLETE.md"
    "BACKUP_METADATA_ANNOTATIONS_REF.md"
)

for doc in "${DOCS[@]}"; do
    if [ -f "$doc" ]; then
        check_pass "Documentation: $doc"
    else
        check_warn "Documentation missing: $doc"
    fi
done

# ============================================================================
# FINAL REPORT
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "FINAL REPORT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✓ All checks passed!${NC}"
    echo ""
    echo "The backup metadata integration is correctly implemented."
    echo ""
    echo "Next steps:"
    echo "  1. Build and push updated images"
    echo "  2. Deploy to test cluster"
    echo "  3. Create test ScanInstance"
    echo "  4. Verify end-to-end flow"
    echo ""
    exit 0
else
    echo -e "${RED}✗ $ERRORS check(s) failed${NC}"
    echo ""
    echo "Please review the errors above and fix before deploying."
    echo ""
    exit 1
fi
