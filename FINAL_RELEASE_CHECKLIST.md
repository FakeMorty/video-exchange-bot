# Final Release Checklist

- [ ] `python -m compileall app` passes without errors
- [ ] `venv\Scripts\python -m app.migrate` runs successfully
- [ ] `/health` command works for admin account
- [ ] Offer flow checked manually:
  - [ ] start offer gives preview reward
  - [ ] subscription verify gives final reward
  - [ ] unsubscribe penalty applies only once
  - [ ] extra penalty never exceeds 50% of paid rewards
- [ ] Broadcast tested from admin panel
- [ ] Promocode activation tested with cooldown behavior
- [ ] Feature flags in `.env` reviewed for production
- [ ] DB backup created (`scripts/backup_db.py`) before release
- [ ] Recovery procedure tested once on a copy
- [ ] Changelog/update message prepared for users/admins
