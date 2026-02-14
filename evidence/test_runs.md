## Test Run 2026-02-14T12:12:30Z
- Status: PASS
- Start: 2026-02-14T12:12:30Z
- End: 2026-02-14T12:12:34Z
- Runtime: python
- Branch: git unavailable
- HEAD: git unavailable
- compileall exit: 0
- import_sanity exit: 0
- pytest exit: 0
- pytest summary: 1 passed, 2 warnings in 0.59s
- git status -sb:
```
## No commits yet on master
A  .env.example
A  .gitignore
A  Contracts/blueprint.md
A  Contracts/boundaries.json
A  Contracts/builder_contract.md
A  Contracts/directive.md
A  Contracts/manifesto.md
A  Contracts/phases.md
A  Contracts/physics.yaml
A  Contracts/schema.md
A  Contracts/stack.md
A  Contracts/system_prompt.md
A  Contracts/templates/blueprint_template.md
A  Contracts/templates/boundaries_template.json
A  Contracts/templates/manifesto_template.md
A  Contracts/templates/phases_template.md
A  Contracts/templates/physics_template.yaml
A  Contracts/templates/schema_template.md
A  Contracts/templates/stack_template.md
A  Contracts/templates/ui_template.md
A  Contracts/ui.md
A  README.md
A  app/__init__.py
A  app/api/__init__.py
A  app/backtest/__init__.py
A  app/broker/__init__.py
A  app/cli/__init__.py
A  app/main.py
A  app/repos/__init__.py
A  app/risk/__init__.py
A  app/strategy/__init__.py
A  data/.gitkeep
A  db/migrations/001_initial_schema.sql
A  evidence/.gitkeep
A  forge.json
A  pytest.ini
A  requirements.txt
A  scripts/overwrite_diff_log.ps1
A  scripts/run_audit.ps1
A  scripts/run_tests.ps1
A  scripts/setup_checklist.ps1
A  tests/__init__.py
A  tests/test_health.py
```
- git diff --stat:
```

```

## Test Run 2026-02-14T12:17:02Z
- Status: PASS
- Start: 2026-02-14T12:17:02Z
- End: 2026-02-14T12:17:05Z
- Runtime: Z:\ForgeTrade\Forge\..\.venv\Scripts\python.exe
- Branch: master
- HEAD: 4819b8fc6b777feb70e8ba104237b71208b4bcff
- import_sanity exit: 0
- compileall exit: 0
- pytest exit: 0
- pytest summary: 11 passed in 1.49s
- git status -sb:
```
## master
 M forge.json
 M pytest.ini
 M requirements.txt
?? app/broker/models.py
?? app/broker/oanda_client.py
?? app/config.py
?? tests/test_broker.py
?? tests/test_config.py
```
- git diff --stat:
```
 forge.json       | 2 +-
 pytest.ini       | 1 +
 requirements.txt | 1 +
 3 files changed, 3 insertions(+), 1 deletion(-)
```

## Test Run 2026-02-14T12:18:00Z
- Status: PASS
- Start: 2026-02-14T12:18:00Z
- End: 2026-02-14T12:18:02Z
- Runtime: Z:\ForgeTrade\Forge\..\.venv\Scripts\python.exe
- Branch: master
- HEAD: 4819b8fc6b777feb70e8ba104237b71208b4bcff
- pytest exit: 0
- import_sanity exit: 0
- compileall exit: 0
- pytest summary: 11 passed in 1.40s
- git status -sb:
```
## master
AM app/broker/models.py
AM app/broker/oanda_client.py
A  app/config.py
 M evidence/audit_ledger.md
M  evidence/test_runs.md
M  evidence/test_runs_latest.md
M  evidence/updatedifflog.md
M  forge.json
M  pytest.ini
M  requirements.txt
A  tests/test_broker.py
A  tests/test_config.py
```
- git diff --stat:
```
 app/broker/models.py       |  2 --
 app/broker/oanda_client.py |  2 --
 evidence/audit_ledger.md   | 38 ++++++++++++++++++++++++++++++++++++++
 3 files changed, 38 insertions(+), 4 deletions(-)
```

## Test Run 2026-02-14T12:20:19Z
- Status: PASS
- Start: 2026-02-14T12:20:19Z
- End: 2026-02-14T12:20:22Z
- Runtime: Z:\ForgeTrade\Forge\..\.venv\Scripts\python.exe
- Branch: master
- HEAD: ea5c72ca134de0c0c2949bda49efc0b515f329ea
- pytest exit: 0
- import_sanity exit: 0
- compileall exit: 0
- pytest summary: 21 passed in 1.41s
- git status -sb:
```
## master
?? app/strategy/indicators.py
?? app/strategy/models.py
?? app/strategy/session_filter.py
?? app/strategy/signals.py
?? app/strategy/sr_zones.py
?? tests/test_strategy.py
```
- git diff --stat:
```

```

## Test Run 2026-02-14T12:27:48Z
- Status: PASS
- Start: 2026-02-14T12:27:48Z
- End: 2026-02-14T12:27:51Z
- Runtime: Z:\ForgeTrade\Forge\..\.venv\Scripts\python.exe
- Branch: master
- HEAD: 7e12afbacfb945135f62c0db2226bd7893866637
- import_sanity exit: 0
- pytest exit: 0
- compileall exit: 0
- pytest summary: 41 passed in 1.47s
- git status -sb:
```
## master
?? app/engine.py
?? app/risk/drawdown.py
?? app/risk/position_sizer.py
?? app/risk/sl_tp.py
?? tests/test_engine.py
?? tests/test_risk.py
```
- git diff --stat:
```

```

## Test Run 2026-02-14T12:31:51Z
- Status: PASS
- Start: 2026-02-14T12:31:51Z
- End: 2026-02-14T12:31:54Z
- Runtime: Z:\ForgeTrade\Forge\..\.venv\Scripts\python.exe
- Branch: master
- HEAD: 3ea18a90a4c7e589b83ac62b2530b860ea11cb53
- compileall exit: 0
- import_sanity exit: 0
- pytest exit: 0
- pytest summary: 51 passed in 1.84s
- git status -sb:
```
## master
 M app/main.py
?? app/api/routers.py
?? app/cli/dashboard.py
?? app/repos/db.py
?? app/repos/equity_repo.py
?? app/repos/trade_repo.py
?? tests/test_phase4.py
```
- git diff --stat:
```
 app/main.py | 5 ++++-
 1 file changed, 4 insertions(+), 1 deletion(-)
```

## Test Run 2026-02-14T12:37:50Z
- Status: PASS
- Start: 2026-02-14T12:37:50Z
- End: 2026-02-14T12:37:54Z
- Runtime: Z:\ForgeTrade\Forge\..\.venv\Scripts\python.exe
- Branch: master
- HEAD: a3deb8b7be3ab64eeb97046079cd1f3d2fed1e82
- compileall exit: 0
- import_sanity exit: 0
- pytest exit: 0
- pytest summary: 58 passed in 1.77s
- git status -sb:
```
## master
?? app/backtest/engine.py
?? app/backtest/stats.py
?? app/repos/backtest_repo.py
?? tests/test_backtest.py
```
- git diff --stat:
```

```

## Test Run 2026-02-14T12:42:50Z
- Status: PASS
- Start: 2026-02-14T12:42:50Z
- End: 2026-02-14T12:42:53Z
- Runtime: Z:\ForgeTrade\Forge\..\.venv\Scripts\python.exe
- Branch: master
- HEAD: 59b9c64662140115789942a06c8cf0b0d850fa93
- compileall exit: 0
- pytest exit: 0
- import_sanity exit: 0
- pytest summary: 63 passed in 1.81s
- git status -sb:
```
## master
 M app/engine.py
 M app/main.py
?? tests/test_integration.py
```
- git diff --stat:
```
 app/engine.py |  48 ++++++++++++++++++++++
 app/main.py   | 125 +++++++++++++++++++++++++++++++++++++++++++++++++++++++++-
 2 files changed, 172 insertions(+), 1 deletion(-)
```

