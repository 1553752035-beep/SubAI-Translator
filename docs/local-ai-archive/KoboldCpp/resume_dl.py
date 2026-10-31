# -*- coding: utf-8 -*-
"""Parallel chunked downloader with resume support (historical verified approach).
Creates a sparse placeholder file first, then fills chunks in parallel.
"""
import os
import sys
import time
import hashlib
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

URLS = [
    "https://hf-mirror.com/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf",
    "https://modelscope.cn/models/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/master/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf",
]
PATH = r"D:\AI\KoboldCpp\models\Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
EXPECT_SHA = "ac0e2c1189e055faa36eff361580e79c5bd6f8e76bffb4ce547f167d53e31a61"
TOTAL = 22134528992
CHUNK = 16 * 1024 * 1024
WORKERS = 32

def download_chunk(args):
    start, end = args
    for attempt in range(5):
        try:
            url = URLS[(start // CHUNK + attempt) % len(URLS)]
            r = requests.get(url, headers={"Range": f"bytes={start}-{end}"}, timeout=90)
            if r.status_code in (200, 206) and len(r.content) == end - start + 1:
                with open(PATH, "r+b") as f:
                    f.seek(start)
                    f.write(r.content)
                return len(r.content)
        except Exception:
            time.sleep(3)
    return 0

def main():
    fresh = "--fresh" in sys.argv
    if fresh or not os.path.exists(PATH):
        if os.path.exists(PATH):
            os.remove(PATH)
        with open(PATH, "wb") as f:
            f.truncate(TOTAL)
    cur = TOTAL  # sparse placeholder; chunks tracked via bitmap file
    bm_path = PATH + ".bitmap"
    total_chunks = (TOTAL + CHUNK - 1) // CHUNK
    if os.path.exists(bm_path):
        with open(bm_path, "rb") as f:
            bm = bytearray(f.read())
    else:
        bm = bytearray(total_chunks)
    if len(bm) < total_chunks:
        bm.extend(b"\x00" * (total_chunks - len(bm)))
    tasks = [i for i in range(total_chunks) if not bm[i]]
    done_bytes = sum(1 for b in bm if b) * CHUNK
    print(f"chunks todo: {len(tasks)}/{total_chunks}, ~{done_bytes/1048576:.0f} MB already done", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(download_chunk, (i * CHUNK, min((i + 1) * CHUNK - 1, TOTAL - 1))): i for i in tasks}
        cnt = 0
        for fut in as_completed(futs):
            i = futs[fut]
            n = fut.result()
            if n > 0:
                bm[i] = 1
                cnt += 1
            if cnt % 32 == 0:
                with open(bm_path, "wb") as f:
                    f.write(bm)
                rate = cnt * CHUNK / max(time.time() - t0, 1) / 1048576
                remain = (len(tasks) - cnt) * CHUNK / 1048576
                print(f"PROGRESS {cnt}/{len(tasks)} chunks  {rate:.1f} MB/s  ETA {remain/max(rate,0.1)/60:.0f} min", flush=True)
    with open(bm_path, "wb") as f:
        f.write(bm)
    missing = sum(1 for b in bm if not b)
    print(f"download finished, missing chunks: {missing}", flush=True)
    if missing == 0:
        print("computing sha256 ...", flush=True)
        h = hashlib.sha256()
        with open(PATH, "rb") as f:
            while True:
                b = f.read(1 << 24)
                if not b:
                    break
                h.update(b)
        got = h.hexdigest()
        print(f"sha256: {got}", flush=True)
        if got == EXPECT_SHA:
            print("SHA OK", flush=True)
            os.remove(bm_path)
        else:
            print("SHA MISMATCH", flush=True)

if __name__ == "__main__":
    main()
