---
name: majorbio-omics-download
description: 美吉云(Majorbio) v.majorbio.com 项目中心组学数据批量下载（SSO登录+图形验证码OCR+腾讯COS预签名直链），scRNA初步质控分析，Word/Excel/PPT三件套报告生成。覆盖登录网关 uc.majorbio.com、数据接口 apix.majorbio.com、文件遍历 file/list、下载 file/download_file、完整性 MD5+gzip 金标准校验、dnbc4tools metrics_summary 解析。
---

# 🧬 美吉组学下载 Skill

> 🎯 **一句话说明**：从美吉云 v.majorbio.com 项目中心登录鉴权、遍历任务、批量下载组学数据到本地，并自动完成 scRNA 初步质控与 Word/Excel/PPT 三件套报告。沉淀了 SSO + 图形验证码 OCR、腾讯 COS 预签名直链下载、完整性金标准校验等关键机制。

## 📖 目录

- [核心铁律](#核心铁律)
- [平台架构](#平台架构)
- [登录鉴权](#登录鉴权)
- [任务列表](#任务列表)
- [文件遍历](#文件遍历)
- [文件下载](#文件下载)
- [完整性校验（金标准）](#完整性校验金标准)
- [scRNA 初步质控分析](#scrna-初步质控分析)
- [三件套报告生成](#三件套报告生成)
- [故障排查决策树](#故障排查决策树)
- [测试记录](#测试记录)
- [速查表](#速查表)
- [参考脚本](#参考脚本)

## 核心铁律

| # | 铁律 | 原因 |
|:--:|------|------|
| 1 | **逐文件下载**（type:"f"），不信任目录批量下载 | 目录下载会漏文件（实测少 4 个），task 根目录报 Undefined index |
| 2 | **下载直链用干净请求**（不带 Authorization 头） | 腾讯 COS 预签名 URL 自带签名，多带头会 400 InvalidArgument |
| 3 | **完整性金标准 = 抽样重下 MD5 逐字节比对 + gzip -t** | manifest 的 size 字段会过期（服务器文件被重新生成），size 不一致 ≠ 损坏 |
| 4 | **编号列 dtype=str** | pandas read_csv 会把 "01" 推断成 1，导致 KeyError |
| 5 | **线粒体比例 0.00% 是特性非异常** | 华大 DNBelab C4 参考基因组未纳入线粒体基因统计 |

## 平台架构

```
登录网关：  uc.majorbio.com      → passport/login（返回 sso token）
数据接口：  apix.majorbio.com    → task/list、file/list、file/download_file
对象存储：  腾讯 COS（S3 兼容）   → file/download_file 返回预签名直链(24h 有效)
```

> 浏览器前端路由标识 `from="uc.mj.com"` 是客户端用的，实际请求体会被 delete，不要被它误导。

鉴权头统一为：

```http
Authorization: <sso token>
X-Requested-With: XMLHttpRequest
```

## 登录鉴权

```bash
# ① 获取图形验证码
curl -s -X POST https://uc.majorbio.com/passport/verify/get_captcha \
  -H 'Content-Type: application/json' -d '{}'
# → {captcha_id, captcha}   captcha 为 data:image/jpeg;base64

# ② 登录
curl -s -X POST https://uc.majorbio.com/passport/login \
  -H 'Content-Type: application/json' \
  -d '{"account":"<账号>","password":"<密码>","captcha":"<OCR结果>","captcha_id":"<captcha_id>","remember":0}'
# 成功 → data.sso（token）
```

| 要点 | 说明 |
|------|------|
| 验证码 | 非内部用户**必须**过图形验证码（isInnerUser 才免） |
| OCR 方案 | `ddddocr`（`pip install ddddocr`），4 位字母数字，命中率约 1/6 |
| 重试策略 | 循环「取验证码 → OCR → 登录」，每次失败重取新验证码 |
| 失败判定 | 返回 code != 0 或 data.sso 为空 → 重试 |

## 任务列表

```bash
curl -s 'https://apix.majorbio.com/task/list/v2?page=1&page_size=50&status=finish' \
  -H 'Authorization: <sso>' -H 'X-Requested-With: XMLHttpRequest'
# → data.lists[]: task_id, title, task_dir_hash, project_dir_hash, is_test, project_sn
```

| 字段 | 说明 |
|------|------|
| task_id | 任务唯一 ID |
| is_test | **2 = 测试数据**（项目中心「测试数据」页签即此）；正式数据为其它值 |
| project_sn | 项目单号（如 MJ20260325286） |
| task_dir_hash / project_dir_hash | 目录哈希，作为 file/list 的 parent_hash 起点 |

## 文件遍历

```bash
curl -s 'https://apix.majorbio.com/file/list?page_size=1000&page=1&level=2&is_project=false&cmd_type=2&parent_hash=<dir_hash>&sort_type=&sort_field=&value=' \
  -H 'Authorization: <sso>' -H 'X-Requested-With: XMLHttpRequest'
# → data.lists[]: {name, type:"d"/"f", dir_hash, file_hash, unique_hash, file_size_name, path}
```

| 参数 | 说明 |
|------|------|
| cmd_type | **2 = 工具数据**（下游分析结果），1 = 原始数据 |
| parent_hash | 目录哈希；根目录用 task_dir_hash，子目录用该项 dir_hash 递归 |
| type | "d"=目录（继续递归），"f"=文件（下载） |

## 文件下载

```bash
# ① 拿预签名直链
curl -s -X POST https://apix.majorbio.com/file/download_file \
  -H 'Authorization: <sso>' -H 'X-Requested-With: XMLHttpRequest' \
  -H 'Content-Type: application/json' \
  -d '{"unique_hash":"<unique_hash>","file_hash":"<file_hash>","type":"f"}'
# → data.file_path（腾讯 COS 预签名直链，24h 有效）
#   若 code=12002 → 文件被平台"上锁"，脚本无法绕过，需 UI 解锁

# ② 下载直链 —— ⚠️ 必须用【不带 Authorization】的干净请求
curl -s -o '<本地路径>' '<file_path>'     # 直接 GET，不加任何鉴权头
```

⚠️ **下载直链千万别带 Authorization 头**——腾讯 COS 预签名 URL 自身已带签名，多带任何鉴权头都会触发 `400 InvalidArgument`。用 `requests.Session()` 空会话 + 仅 User-Agent，或纯 `curl`。

| 注意 | 说明 |
|------|------|
| 目录下载 type:"d" | 会返回文件 URL 列表但**可能不全**，且 task 根目录报 Undefined index → 弃用 |
| 直链有效期 | 24h，超时需重新调 download_file |
| 断点续传 | 用 .part 临时文件 + 完成后 rename，支持重跑 |

## 完整性校验（金标准）

```
下载完成后三层校验：
1. 文件数：磁盘文件数 == manifest 文件数，且无 .part 残留
2. gzip 完整性：所有 .gz 跑 gzip -t，必须 0 损坏
3. 内容一致性：抽样重下 N 个文件，逐字节 MD5 与磁盘比对，必须 100% 一致
```

⚠️ **不要用 manifest 的 size 字段做严格比对**——美吉云 file/list 返回的 size 是文件首次索引时的旧值，服务器文件被下游流程重新生成后大小已变（gz 差 1~5 字节、matrix 差几百字节），size 不一致是**平台数据过期**，不是下载损坏。

## scRNA 初步质控分析

### 数据来源

每个样本目录下 `workflow_results/01_BasicAnalysis/Dnbc4tools/metrics_summary.csv`，22 列：

```
sample, Estimated number of cell, Mean reads per cell, Mean UMI count per cell,
Median UMI counts per cell, Total genes detected, Mean genes per cell,
Median genes per cell, Sequencing saturation, Fraction Reads in cell,
cDNA Number of reads, cDNA Reads pass QC, cDNA Adapter Reads, cDNA Q30 bases in reads,
index Number of reads, index Reads pass QC, index Q30 bases in reads,
Mitochondria ratio, Reads mapped to genome, Reads mapped to exonic regions,
Reads mapped to intronic regions, Reads mapped antisense to gene,
Reads mapped to intergenic regions
```

### 关键指标与判读

| 指标 | 字段 | 正常范围 |
|------|------|------|
| 细胞数 | Estimated number of cell | 数千~数万/样本 |
| Reads/细胞 | Mean reads per cell | 1 万~8 万 |
| UMI/细胞 | Mean UMI count per cell | 3k~9k |
| 基因/细胞 | Mean genes per cell | 1.5k~2.5k |
| cDNA Q30 | cDNA Q30 bases in reads | >90% |
| index Q30 | index Q30 bases in reads | >98% |
| 饱和度 | Sequencing saturation | 50%~95% |
| 细胞捕获率 | Fraction Reads in cell | >70% |
| 基因组比对率 | Reads mapped to genome | 65%~90% |
| 线粒体比例 | Mitochondria ratio | **华大 C4 常为 0.00%** |

### 平台特性

- 平台：**华大 DNBelab C4**（Dnbc4tools v2.x 分析）
- **线粒体比例 0.00%**：参考基因组未纳入线粒体基因统计，属平台特性，非数据异常（不要据此判样本坏死）
- 样本命名规律 → 分组推测（如 `_1` 后缀=重复/批次、`OPF_1~4`=四重复），推测必须标注「待确认」

## 三件套报告生成

| 格式 | 库 | 内容 |
|------|-----|------|
| Word | python-docx | 概述 + 逐项目/逐样本明细表 + 图表 |
| Excel | openpyxl | 多 Sheet：概览/汇总统计/样本明细/分组说明 |
| PPT | python-pptx | 封面 + 关键结论 + 统计图 |

### 图表中文（关键）

```python
import matplotlib
from matplotlib import font_manager
for f in ["/mnt/c/Windows/Fonts/msyh.ttc", "/mnt/c/Windows/Fonts/msyhbd.ttc"]:
    font_manager.fontManager.addfont(f)
plt.rcParams["font.family"] = font_manager.FontProperties(fname="/mnt/c/Windows/Fonts/msyh.ttc").get_name()
plt.rcParams["axes.unicode_minus"] = False   # 负号正常显示
```

### pandas 前导零

```python
import pandas as pd
df = pd.read_csv(csv, dtype=str)   # 编号列 "01" 不会被推断成 1
```

## 故障排查决策树

```
下载直链 400 InvalidArgument
  └─ 带了 Authorization/多余头 → 去掉，用干净 GET

file/download_file 返回 code 12002
  └─ 文件被平台"上锁" → 脚本无法绕过 → 用户到 v.majorbio.com UI 解锁后重试

登录失败 / 验证码识别不对
  ├─ ddddocr 命中率约 1/6 → 循环重试（每次重取新验证码）
  └─ 确认 account/password 正确、非内部用户必须有验证码

manifest size 与磁盘不一致
  └─ 平台 size 字段过期，非损坏 → 用 MD5 抽样重下 + gzip -t 验证

matplotlib 图表中文豆腐块
  └─ 未注册中文字体 → fontManager.addfont(msyh.ttc) + rcParams 设置

pandas KeyError / 编号前导零丢失
  └─ read_csv 推断类型 → 加 dtype=str

gzip -t 报错
  └─ 文件确实损坏/未下全 → 删除该文件重下（断点续传 .part）
```

## 测试记录

| 日期 | 任务 | 结果 |
|------|------|------|
| 2026-08 | 4 个测试任务（小鼠4 scRNA / 食蟹猴12 scRNA / 食蟹猴35 scRNA / 小鼠18 DIA） | 1753 文件 13.3GB，1752 成功，1 个 seq_db.sqlite3 被平台锁定 |
| 2026-09 | 食蟹猴20样本 scRNA（MJ20260325286） | 144 文件 1.18GB 全部成功，gzip 60/60 通过 |

## 速查表

| 操作 | 命令/要点 |
|------|------|
| 取验证码 | POST uc.majorbio.com/passport/verify/get_captcha |
| 登录 | POST uc.majorbio.com/passport/login → data.sso |
| 鉴权头 | Authorization: \<sso\> + X-Requested-With: XMLHttpRequest |
| 任务列表 | GET apix.majorbio.com/task/list/v2（is_test=2 为测试数据） |
| 文件遍历 | GET apix.majorbio.com/file/list（cmd_type=2 工具数据） |
| 拿直链 | POST apix.majorbio.com/file/download_file（type:"f"） |
| 下载直链 | 干净 GET，不带 Authorization |
| 完整性 | 文件数 + gzip -t + MD5 抽样重下 |
| OCR | ddddocr，4 位字母数字，命中率 ~1/6，循环重试 |
| 中文字体 | fontManager.addfont(msyh.ttc) |
| 前导零 | read_csv(dtype=str) |

## 参考脚本

| 脚本 | 用途 |
|------|------|
| `scripts/majorbio_download.py` | 登录 + 遍历 + 逐文件下载（无硬编码凭据，账号密码走 CLI/env） |
| `scripts/scRNA_qc_report.py` | metrics_summary 解析 + 图表 + 三件套报告（无硬编码凭据） |

> 🔐 账号密码属敏感信息：脚本一律从 `--account/--password` 或环境变量 `MAJORBIO_ACCOUNT/MAJORBIO_PASSWORD` 读取，绝不硬编码，不写入 Git 历史。
