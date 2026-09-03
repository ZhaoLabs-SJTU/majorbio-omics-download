#!/usr/bin/env python3
"""美吉云(Majorbio) v.majorbio.com 组学数据批量下载器。

用法:
    python majorbio_download.py --account <账号> --password <密码> --outdir <输出目录> [选项]

凭据也可用环境变量: MAJORBIO_ACCOUNT / MAJORBIO_PASSWORD（不硬编码、不进 Git 历史）。

关键机制:
  - 登录网关 uc.majorbio.com（图形验证码用 ddddocr 自动 OCR，循环重试）
  - 数据接口 apix.majorbio.com（Authorization + X-Requested-With）
  - 逐文件 type:"f" 下载（目录批量下载会漏文件）
  - 下载直链必须用【不带 Authorization】的干净请求（否则 400 InvalidArgument）
"""
import argparse
import base64
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

try:
    import ddddocr
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

API_UC = "https://uc.majorbio.com"
API_APIX = "https://apix.majorbio.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


class MajorbioClient:
    def __init__(self, account, password):
        self.account = account
        self.password = password
        self.sso = None
        self.ocr = ddddocr.DdddOcr(show_ad=False) if HAS_OCR else None

    def _headers(self):
        return {"Authorization": self.sso, "X-Requested-With": "XMLHttpRequest", "User-Agent": UA}

    def _get_captcha(self):
        r = requests.post(f"{API_UC}/passport/verify/get_captcha", json={}, timeout=30)
        d = r.json()
        return d["captcha_id"], d["captcha"]

    def _captcha_to_text(self, captcha_b64):
        img = base64.b64decode(captcha_b64.split(",", 1)[-1])
        return self.ocr.classification(img)

    def login(self, max_tries=30):
        """登录，返回 (成功?, sso)。验证码 OCR 命中率约 1/6，需循环重试。"""
        for i in range(1, max_tries + 1):
            try:
                cid, cap = self._get_captcha()
                code = self._captcha_to_text(cap) if HAS_OCR else input("未安装 ddddocr，请手动输入验证码: ")
            except Exception as e:
                print(f"[login] 取验证码失败: {e}", file=sys.stderr)
                time.sleep(1)
                continue
            try:
                r = requests.post(f"{API_UC}/passport/login", json={
                    "account": self.account, "password": self.password,
                    "captcha": code, "captcha_id": cid, "remember": 0}, timeout=30)
                d = r.json()
            except Exception as e:
                print(f"[login] 请求失败: {e}", file=sys.stderr)
                time.sleep(1)
                continue
            if d.get("code") == 0 and d.get("data", {}).get("sso"):
                self.sso = d["data"]["sso"]
                print(f"[login] 成功 (第 {i} 次)", file=sys.stderr)
                return True
            print(f"[login] 第 {i} 次失败: {d.get('msg')} / code={d.get('code')}", file=sys.stderr)
            time.sleep(0.5)
        return False

    def list_tasks(self, status="finish", page_size=100):
        """列出已完成任务。is_test==2 为测试数据。"""
        r = requests.get(f"{API_APIX}/task/list/v2",
                         params={"page": 1, "page_size": page_size, "status": status},
                         headers=self._headers(), timeout=30)
        return r.json().get("data", {}).get("lists", []) or []

    def list_files(self, parent_hash, cmd_type=2):
        """递归遍历目录，返回文件项列表 [{name,path,unique_hash,file_hash,file_size_name}]。"""
        files, stack = [], [parent_hash]
        while stack:
            ph = stack.pop()
            page = 1
            while True:
                params = {"page_size": 1000, "page": page, "level": 2, "is_project": "false",
                          "cmd_type": cmd_type, "parent_hash": ph,
                          "sort_type": "", "sort_field": "", "value": ""}
                r = requests.get(f"{API_APIX}/file/list", params=params, headers=self._headers(), timeout=30)
                data = r.json().get("data", {}) or {}
                items = data.get("lists", [])
                if not items:
                    break
                for it in items:
                    if it.get("type") == "d":
                        stack.append(it.get("dir_hash"))
                    else:
                        files.append(it)
                if len(items) < 1000:
                    break
                page += 1
        return files

    def get_download_url(self, item):
        """拿预签名直链；code==12002 为文件被平台锁定，返回 None。"""
        r = requests.post(f"{API_APIX}/file/download_file",
                          json={"unique_hash": item["unique_hash"],
                                "file_hash": item["file_hash"], "type": "f"},
                          headers=self._headers(), timeout=30)
        d = r.json()
        if d.get("code") == 0 and d.get("data", {}).get("file_path"):
            return d["data"]["file_path"]
        print(f"[url] 失败 {item.get('path')}: code={d.get('code')} {d.get('msg')}", file=sys.stderr)
        return None

    def download_one(self, url, dest):
        """下载直链到 dest（干净请求，无 Authorization）。返回字节数。"""
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        part = dest + ".part"
        # 关键：只带 UA，不带 Authorization，否则 400 InvalidArgument
        with requests.get(url, stream=True, timeout=180, headers={"User-Agent": UA}) as r:
            r.raise_for_status()
            with open(part, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        os.replace(part, dest)
        return os.path.getsize(dest)


def main():
    ap = argparse.ArgumentParser(description="美吉云组学数据批量下载")
    ap.add_argument("--account", default=os.environ.get("MAJORBIO_ACCOUNT"))
    ap.add_argument("--password", default=os.environ.get("MAJORBIO_PASSWORD"))
    ap.add_argument("--outdir", required=True, help="输出根目录")
    ap.add_argument("--task-id", action="append", default=None, type=int,
                    help="只下载指定 task_id（可多次）；缺省下载全部 is_test==2 的测试任务")
    ap.add_argument("--workers", type=int, default=8, help="并发数")
    ap.add_argument("--cmd-type", type=int, default=2, help="2=工具数据, 1=原始数据")
    ap.add_argument("--manifest", default="manifest.json", help="清单文件路径")
    args = ap.parse_args()

    if not args.account or not args.password:
        ap.error("缺少账号密码：用 --account/--password 或 MAJORBIO_ACCOUNT/MAJORBIO_PASSWORD")

    c = MajorbioClient(args.account, args.password)
    if not c.login():
        sys.exit("登录失败")

    tasks = c.list_tasks()
    if args.task_id:
        tasks = [t for t in tasks if t.get("task_id") in args.task_id]
    else:
        tasks = [t for t in tasks if t.get("is_test") == 2]
    print(f"[tasks] 共 {len(tasks)} 个任务", file=sys.stderr)

    # 收集所有文件
    all_files = []
    for t in tasks:
        tid = t.get("task_id")
        root = t.get("task_dir_hash") or t.get("project_dir_hash")
        files = c.list_files(root, cmd_type=args.cmd_type)
        for f in files:
            f["_task_id"] = tid
            f["_title"] = t.get("title", "")
        all_files.extend(files)
        print(f"[task {tid}] {t.get('title')} -> {len(files)} 文件", file=sys.stderr)

    with open(args.manifest, "w", encoding="utf-8") as fh:
        json.dump(all_files, fh, ensure_ascii=False, indent=2)

    done = skip = fail = 0
    total_bytes = 0
    failures = []

    def work(f):
        path = f.get("path") or f.get("name")
        dest = os.path.join(args.outdir, path.lstrip("/"))
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            return ("skip", path, 0)
        url = c.get_download_url(f)
        if not url:
            return ("fail", path, 0)
        n = c.download_one(url, dest)
        return ("done", path, n)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, f): f for f in all_files}
        for fut in as_completed(futs):
            st, path, n = fut.result()
            if st == "done":
                done += 1
                total_bytes += n
            elif st == "skip":
                skip += 1
            else:
                fail += 1
                failures.append(path)
            print(f"\r[进度] done={done} skip={skip} fail={fail} bytes={total_bytes/1e6:.1f}MB",
                  end="", file=sys.stderr, flush=True)

    print(file=sys.stderr)
    print(f"\n完成: done={done} skip={skip} fail={fail} 共 {total_bytes/1e6:.1f}MB")
    if failures:
        with open("failures.json", "w", encoding="utf-8") as fh:
            json.dump(failures, fh, ensure_ascii=False, indent=2)
        print(f"失败清单: {len(failures)} 个 → failures.json")


if __name__ == "__main__":
    main()
