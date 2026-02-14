Status: PASS
Start: 2026-02-14T12:18:00Z
End: 2026-02-14T12:18:02Z
Branch: master
HEAD: 4819b8fc6b777feb70e8ba104237b71208b4bcff
Runtime: Z:\ForgeTrade\Forge\..\.venv\Scripts\python.exe
pytest exit: 0
import_sanity exit: 0
compileall exit: 0
pytest summary: 11 passed in 1.40s
git status -sb:
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
git diff --stat:
```
 app/broker/models.py       |  2 --
 app/broker/oanda_client.py |  2 --
 evidence/audit_ledger.md   | 38 ++++++++++++++++++++++++++++++++++++++
 3 files changed, 38 insertions(+), 4 deletions(-)
```

