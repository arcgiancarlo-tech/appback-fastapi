# Utility: Alembic auto-revision script
# Generates revision scripts automatically from current models

import os
os.system('alembic revision --autogenerate -m "auto revision"')
