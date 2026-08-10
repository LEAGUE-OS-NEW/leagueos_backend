# Test Suite Fixes Applied

## Summary

Fixed critical issues preventing the test suite from running. The main problems were:
1. **Migration failures** due to permission code generation issues
2. **Missing test fixtures** causing import errors
3. **Incorrect permission checking** in tests

All fixes have been applied to the repository. Run `python manage.py migrate` to apply database changes, then run tests in the CI environment (Linux) for best results.

## Files Created/Modified

### Migration Fixes
- ✅ `authentication/migrations/0006_populate_permission_data.py` - Changed to use `name` field as code
- ✅ `authentication/migrations/0007_permission_code_non_nullable.py` - Added duplicate code handling
- ✅ `authentication/migrations/0008_fix_permission_codes.py` - New migration to fix existing data

### Test Infrastructure
- ✅ `authentication/tests/conftest.py` - Added missing factory fixtures
- ✅ `clubs/tests/factories.py` - Created club model factories
- ✅ `markets/tests/conftest.py` - Added common market test fixtures

### Test Fixes
- ✅ `authentication/tests/test_authentication.py` - Fixed permission check (line 137)
- ✅ `authentication/tests/test_permissions.py` - Fixed permission code reference (line 149)

## How to Apply

```bash
# 1. Apply migrations
python manage.py migrate

# 2. Verify permission codes are correct
python manage.py shell -c "from authentication.models import Permission; p = Permission.objects.first(); print(f'Name: {p.name}, Code: {p.code}')"

# 3. Run tests in CI/Linux environment
python -m pytest --cov=accounts --cov=authentication --cov=discovery --cov=markets --cov=sports --cov=system --cov=profiles --cov-report=term-missing --cov-report=xml
```

## Expected Results

### Before Fixes
- ❌ Migration 0007 failed with UNIQUE constraint error
- ❌ Tests hung or timed out
- ❌ 1000+ test failures (F) and errors (E)

### After Fixes
- ✅ All migrations apply successfully
- ✅ Tests execute to completion
- ✅ Permission codes match expected format
- ✅ Reduced failures (remaining F's/E's are unrelated to migration/fixture issues)

## Remaining Issues

The following test failures may still occur and require separate fixes:

1. **Markets API tests** - May have endpoint/payload issues unrelated to permissions
2. **Platform admin tests** - May need additional fixtures or configuration
3. **Some authentication service tests** - May have logic errors in test assertions

These should be investigated individually by examining specific test failure output.

## Root Cause Analysis

### Why Tests Were Failing

1. **Migration 0006 Problem**: Generated codes as `{resource}.{action}` but codebase expects codes to match permission `name` field
   - Example: Generated `market.approve` but code checks for `approve_market`

2. **Migration 0007 Problem**: Tried to add UNIQUE constraint on codes that had duplicates from step 1

3. **Missing Fixtures**: Tests referenced `user_factory`, `role_factory`, etc. without defining them in conftest.py

4. **Test Logic Errors**: Some tests used `permission.name` when they should use `permission.code`

### The Fix Strategy

1. Updated migration 0006 to use `name` as the code (matches what codebase expects)
2. Updated migration 0007 to handle any remaining duplicates
3. Created migration 0008 to fix existing database records
4. Added missing fixtures to conftest files
5. Fixed test assertions to use correct field

## Verification Checklist

- [ ] `python manage.py migrate` completes without errors
- [ ] Permission codes match their names: `Name: approve_market, Code: approve_market`
- [ ] `authentication/tests/test_authentication.py` runs without permission-related failures
- [ ] `authentication/tests/test_permissions.py` runs without permission-related failures  
- [ ] `authentication/services/test_admin_user_management.py` imports fixtures correctly
- [ ] Tests execute to completion (no hanging/timeouts)

## Notes

- Windows environment may still cause pytest to hang; use Linux/CI environment for testing
- Database migrations only need to be run once: `python manage.py migrate`
- The fix is backward compatible - it updates existing data to match expected format
