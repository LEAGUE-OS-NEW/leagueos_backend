# TODO: Fix WalletService / LedgerEntry CI failures

## Goal
Resolve the 292 failing tests caused by the `wallets` app having an incompatible
`LedgerEntry` schema and `WalletService` API compared to what the `markets` app expects.

## Steps
- [ ] 1. Create `wallets/exceptions.py` with custom exception classes
- [ ] 2. Rewrite `wallets/models.py` `LedgerEntry` model + `Wallet` updates
- [ ] 3. Delete redundant `markets/services/wallet_service.py` (dead reference impl importing missing `wallets.exceptions`)
- [ ] 4. Create new migration `0003` for schema changes
- [ ] 5. Rewrite `wallets/services/wallet_service.py`
- [ ] 6. Update `wallets/services/wallet_read_service.py`
- [ ] 7. Update `wallets/serializers.py`
- [ ] 8. Update `wallets/views.py`
- [ ] 9. Update `wallets/tests/factories.py`
- [ ] 10. Run `pytest wallets -x` to validate
- [ ] 11. Run `pytest markets -x` to validate
- [ ] 12. Run ruff/black to ensure lint passes
