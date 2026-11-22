import os

# Limity czasu testów wydajności są dobrane na szybkiej maszynie; wolniejsze środowiska mnożą je przez ten współczynnik.
TIME_LIMIT_SCALE = float(os.getenv("PERF_TIME_SCALE") or (2.0 if os.getenv("CI") else 1.5))
