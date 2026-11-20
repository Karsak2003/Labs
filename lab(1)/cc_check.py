import time, httpx
for p in ("*pstu.ru*", "*.pstu.ru"):
    t = time.time()
    try:
        r = httpx.get("https://index.commoncrawl.org/CC-MAIN-2024-10-index",
                      params={"url": p, "output": "json", "limit": 2}, timeout=30)
        print(p, "->", r.status_code, round(time.time() - t, 1), "s")
    except Exception as e:
        print(p, "-> FAIL", round(time.time() - t, 1), "s", e)